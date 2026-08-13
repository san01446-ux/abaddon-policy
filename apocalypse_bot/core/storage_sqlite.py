from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

DEFAULT_DB_PATH = os.getenv("ABADDON_DB_PATH", "/var/data/abaddon.sqlite3")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path(path: Optional[str] = None) -> Path:
    return Path(path or os.getenv("ABADDON_DB_PATH") or DEFAULT_DB_PATH)


def _connect(path: Optional[str] = None) -> sqlite3.Connection:
    target = _db_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=12)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize(path: Optional[str] = None) -> str:
    target = _db_path(path)
    with _connect(str(target)) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS user_snapshots (
                user_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS world_snapshot (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS migration_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                users_count INTEGER NOT NULL,
                world_keys INTEGER NOT NULL,
                source_json TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                guild_id TEXT NOT NULL,
                command TEXT NOT NULL,
                source TEXT NOT NULL,
                ok INTEGER NOT NULL,
                duration_ms REAL NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_usage_events_guild_ts ON usage_events(guild_id, ts DESC);
            CREATE INDEX IF NOT EXISTS idx_usage_events_ts ON usage_events(ts DESC);
            CREATE TABLE IF NOT EXISTS usage_guild_stats (
                guild_id TEXT PRIMARY KEY,
                runs INTEGER NOT NULL DEFAULT 0,
                success INTEGER NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0,
                prefix INTEGER NOT NULL DEFAULT 0,
                button INTEGER NOT NULL DEFAULT 0,
                interaction INTEGER NOT NULL DEFAULT 0,
                last_ts REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS usage_command_stats (
                guild_id TEXT NOT NULL,
                command TEXT NOT NULL,
                runs INTEGER NOT NULL DEFAULT 0,
                success INTEGER NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0,
                prefix INTEGER NOT NULL DEFAULT 0,
                button INTEGER NOT NULL DEFAULT 0,
                interaction INTEGER NOT NULL DEFAULT 0,
                last_ts REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(guild_id, command)
            );
            CREATE INDEX IF NOT EXISTS idx_usage_command_runs ON usage_command_stats(guild_id, runs DESC);
            """
        )
        conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('schema_version','2')")
        conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('last_initialized',?)", (_now(),))
    return str(target)


def mirror_snapshot(users: Mapping[str, Any], world: Mapping[str, Any], *, source_json: str = "", path: Optional[str] = None) -> Dict[str, Any]:
    target = initialize(path)
    stamp = _now()
    user_rows = 0
    with _connect(target) as conn:
        for user_id, payload in users.items():
            if not isinstance(payload, Mapping):
                continue
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            conn.execute(
                "INSERT INTO user_snapshots(user_id,payload_json,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at",
                (str(user_id), raw, stamp),
            )
            user_rows += 1
        world_raw = json.dumps(dict(world), ensure_ascii=False, separators=(",", ":"))
        conn.execute(
            "INSERT INTO world_snapshot(id,payload_json,updated_at) VALUES(1,?,?) "
            "ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at",
            (world_raw, stamp),
        )
        conn.execute(
            "INSERT INTO migration_log(created_at,users_count,world_keys,source_json) VALUES(?,?,?,?)",
            (stamp, user_rows, len(world) if isinstance(world, Mapping) else 0, str(source_json or "")[:500]),
        )
        conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('last_mirror',?)", (stamp,))
    return {"ok": True, "path": target, "users": user_rows, "world_keys": len(world), "updated_at": stamp}


def load_snapshot(path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    target = _db_path(path)
    if not target.is_file():
        return None
    try:
        with _connect(str(target)) as conn:
            world_row = conn.execute("SELECT payload_json FROM world_snapshot WHERE id=1").fetchone()
            user_rows = conn.execute("SELECT user_id,payload_json FROM user_snapshots").fetchall()
        if not world_row:
            return None
        world = json.loads(world_row[0])
        users: Dict[str, Any] = {}
        for user_id, raw in user_rows:
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            if isinstance(payload, dict):
                users[str(user_id)] = payload
        if not isinstance(world, dict):
            return None
        return {"users": users, "world": world}
    except Exception:
        return None


def audit(path: Optional[str] = None) -> Dict[str, Any]:
    target = _db_path(path)
    if not target.is_file():
        return {"ok": False, "path": str(target), "error": "database_missing"}
    try:
        with _connect(str(target)) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            users = conn.execute("SELECT COUNT(*) FROM user_snapshots").fetchone()[0]
            world = conn.execute("SELECT COUNT(*) FROM world_snapshot").fetchone()[0]
            meta = dict(conn.execute("SELECT key,value FROM metadata").fetchall())
            migrations = conn.execute("SELECT COUNT(*) FROM migration_log").fetchone()[0]
        ok = bool(integrity and str(integrity[0]).lower() == "ok" and world == 1)
        return {
            "ok": ok,
            "path": str(target),
            "integrity": integrity[0] if integrity else "unknown",
            "users": int(users),
            "world_rows": int(world),
            "migrations": int(migrations),
            "last_mirror": meta.get("last_mirror", ""),
            "schema_version": meta.get("schema_version", ""),
            "size": target.stat().st_size,
        }
    except Exception as exc:
        return {"ok": False, "path": str(target), "error": f"{type(exc).__name__}: {exc}"}


# v18.2.0: operational usage telemetry is stored separately from the large JSON
# snapshot so normal command/button traffic no longer forces full JSON rewrites.
def record_usage_event(
    guild_id: int | str,
    command: str,
    source: str,
    ok: bool,
    duration_ms: float = 0.0,
    error: str = "",
    *,
    ts: Optional[float] = None,
    event_limit: int = 2500,
    path: Optional[str] = None,
) -> Dict[str, Any]:
    target = initialize(path)
    gid = str(guild_id)
    cmd = str(command or "unknown")[:100]
    src = str(source or "prefix")[:24]
    when = float(ts if ts is not None else datetime.now(timezone.utc).timestamp())
    good = 1 if bool(ok) else 0
    bad = 0 if good else 1
    prefix = 1 if src == "prefix" else 0
    button = 1 if src == "button" else 0
    interaction = 1 if src == "interaction" else 0
    with _connect(target) as conn:
        cursor = conn.execute(
            "INSERT INTO usage_events(ts,guild_id,command,source,ok,duration_ms,error) VALUES(?,?,?,?,?,?,?)",
            (when, gid, cmd, src, good, max(0.0, float(duration_ms)), str(error or "")[:120]),
        )
        conn.execute(
            """
            INSERT INTO usage_guild_stats(guild_id,runs,success,failures,prefix,button,interaction,last_ts)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(guild_id) DO UPDATE SET
                runs=usage_guild_stats.runs+1,
                success=usage_guild_stats.success+excluded.success,
                failures=usage_guild_stats.failures+excluded.failures,
                prefix=usage_guild_stats.prefix+excluded.prefix,
                button=usage_guild_stats.button+excluded.button,
                interaction=usage_guild_stats.interaction+excluded.interaction,
                last_ts=MAX(usage_guild_stats.last_ts, excluded.last_ts)
            """,
            (gid, 1, good, bad, prefix, button, interaction, when),
        )
        conn.execute(
            """
            INSERT INTO usage_command_stats(guild_id,command,runs,success,failures,prefix,button,interaction,last_ts)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(guild_id,command) DO UPDATE SET
                runs=usage_command_stats.runs+1,
                success=usage_command_stats.success+excluded.success,
                failures=usage_command_stats.failures+excluded.failures,
                prefix=usage_command_stats.prefix+excluded.prefix,
                button=usage_command_stats.button+excluded.button,
                interaction=usage_command_stats.interaction+excluded.interaction,
                last_ts=MAX(usage_command_stats.last_ts, excluded.last_ts)
            """,
            (gid, cmd, 1, good, bad, prefix, button, interaction, when),
        )
        row_id = int(cursor.lastrowid or 0)
        if event_limit > 0 and row_id and row_id % 100 == 0:
            conn.execute(
                "DELETE FROM usage_events WHERE id NOT IN (SELECT id FROM usage_events ORDER BY id DESC LIMIT ?)",
                (int(event_limit),),
            )
    return {"ok": True, "path": target, "event_id": row_id}


def recent_usage_events(
    *,
    guild_id: Optional[int | str] = None,
    limit: int = 25,
    since_ts: Optional[float] = None,
    path: Optional[str] = None,
) -> list[Dict[str, Any]]:
    target = initialize(path)
    where = []
    args: list[Any] = []
    if guild_id is not None:
        where.append("guild_id=?")
        args.append(str(guild_id))
    if since_ts is not None:
        where.append("ts>=?")
        args.append(float(since_ts))
    clause = " WHERE " + " AND ".join(where) if where else ""
    args.append(max(1, min(int(limit), 2500)))
    with _connect(target) as conn:
        rows = conn.execute(
            "SELECT ts,guild_id,command,source,ok,duration_ms,error FROM usage_events"
            + clause + " ORDER BY id DESC LIMIT ?",
            tuple(args),
        ).fetchall()
    return [
        {
            "ts": float(row[0]), "guild_id": str(row[1]), "command": str(row[2]),
            "source": str(row[3]), "ok": bool(row[4]), "ms": float(row[5]), "error": str(row[6] or ""),
        }
        for row in rows
    ]


def usage_guild_overview(path: Optional[str] = None) -> list[Dict[str, Any]]:
    target = initialize(path)
    with _connect(target) as conn:
        rows = conn.execute(
            "SELECT guild_id,runs,success,failures,prefix,button,interaction,last_ts "
            "FROM usage_guild_stats ORDER BY runs DESC"
        ).fetchall()
    keys = ("guild_id", "runs", "success", "failures", "prefix", "button", "interaction", "last_ts")
    return [dict(zip(keys, row)) for row in rows]


def usage_guild_detail(guild_id: int | str, *, command_limit: int = 15, path: Optional[str] = None) -> Dict[str, Any]:
    target = initialize(path)
    gid = str(guild_id)
    with _connect(target) as conn:
        row = conn.execute(
            "SELECT guild_id,runs,success,failures,prefix,button,interaction,last_ts FROM usage_guild_stats WHERE guild_id=?",
            (gid,),
        ).fetchone()
        commands_rows = conn.execute(
            "SELECT command,runs,success,failures,prefix,button,interaction,last_ts "
            "FROM usage_command_stats WHERE guild_id=? ORDER BY runs DESC,last_ts DESC LIMIT ?",
            (gid, max(1, min(int(command_limit), 300))),
        ).fetchall()
    if not row:
        return {}
    keys = ("guild_id", "runs", "success", "failures", "prefix", "button", "interaction", "last_ts")
    result = dict(zip(keys, row))
    ckeys = ("command", "runs", "success", "failures", "prefix", "button", "interaction", "last_ts")
    result["commands"] = [dict(zip(ckeys, item)) for item in commands_rows]
    return result


def usage_event_count(path: Optional[str] = None) -> int:
    target = initialize(path)
    with _connect(target) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0])


def migrate_legacy_usage(legacy_root: Mapping[str, Any], *, path: Optional[str] = None) -> Dict[str, Any]:
    """One-time import of v18.1.5 JSON telemetry into the dedicated SQLite tables."""
    target = initialize(path)
    if not isinstance(legacy_root, Mapping):
        return {"ok": True, "migrated": False, "events": 0, "guilds": 0, "path": target}
    with _connect(target) as conn:
        marker = conn.execute("SELECT value FROM metadata WHERE key='usage_v1815_migrated'").fetchone()
        if marker:
            return {"ok": True, "migrated": False, "events": 0, "guilds": 0, "path": target}
        events = legacy_root.get("events", []) if isinstance(legacy_root.get("events"), list) else []
        for event in events:
            if not isinstance(event, Mapping):
                continue
            conn.execute(
                "INSERT INTO usage_events(ts,guild_id,command,source,ok,duration_ms,error) VALUES(?,?,?,?,?,?,?)",
                (
                    float(event.get("ts", 0.0) or 0.0), str(event.get("guild_id", "0")),
                    str(event.get("command", "unknown"))[:100], str(event.get("source", "prefix"))[:24],
                    1 if bool(event.get("ok")) else 0, float(event.get("ms", 0.0) or 0.0),
                    str(event.get("error", ""))[:120],
                ),
            )
        guild_stats = legacy_root.get("guild_stats", {}) if isinstance(legacy_root.get("guild_stats"), Mapping) else {}
        guild_count = 0
        for gid, stats in guild_stats.items():
            if not isinstance(stats, Mapping):
                continue
            guild_count += 1
            conn.execute(
                "INSERT OR REPLACE INTO usage_guild_stats(guild_id,runs,success,failures,prefix,button,interaction,last_ts) VALUES(?,?,?,?,?,?,?,?)",
                (
                    str(gid), int(stats.get("runs", 0) or 0), int(stats.get("success", 0) or 0),
                    int(stats.get("failures", 0) or 0), int(stats.get("prefix", 0) or 0),
                    int(stats.get("button", 0) or 0), int(stats.get("interaction", 0) or 0),
                    float(stats.get("last_ts", 0.0) or 0.0),
                ),
            )
            commands_map = stats.get("commands", {}) if isinstance(stats.get("commands"), Mapping) else {}
            for command, row in commands_map.items():
                if not isinstance(row, Mapping):
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO usage_command_stats(guild_id,command,runs,success,failures,prefix,button,interaction,last_ts) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        str(gid), str(command)[:100], int(row.get("runs", 0) or 0), int(row.get("success", 0) or 0),
                        int(row.get("failures", 0) or 0), int(row.get("prefix", 0) or 0), int(row.get("button", 0) or 0),
                        int(row.get("interaction", 0) or 0), float(row.get("last_ts", 0.0) or 0.0),
                    ),
                )
        conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('usage_v1815_migrated',?)", (_now(),))
        conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('usage_storage','sqlite')")
    return {"ok": True, "migrated": True, "events": len(events), "guilds": guild_count, "path": target}
