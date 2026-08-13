from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v1811_presence_owner_servers import _private_owner
from apocalypse_bot.core.storage_sqlite import (
    initialize as initialize_sqlite,
    migrate_legacy_usage,
    recent_usage_events,
    record_usage_event,
    usage_event_count,
    usage_guild_detail,
    usage_guild_overview,
)

VERSION = "18.2.1"
ROOT_KEY = "owner_usage_v1815"
EVENT_LIMIT = 2500
FALLBACK_SAVE_EVERY = 20
OWNER_COMMANDS = {
    "내서버목록", "한국봇상태", "1811상태검수", "운영통계", "실사용통계",
    "서버사용로그", "서버사용통계", "1815사용로그검수", "봇검수", "프로덕션검수", "정리현황",
    "생존자명단", "생존자수", "생존자검색", "1821검수",
    "오류DM테스트", "오류알림상태", "자동오류최근", "1833오류검수",
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _legacy_root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault(ROOT_KEY, {})
    if not isinstance(root, dict):
        root = {}
        world_data[ROOT_KEY] = root
    root.setdefault("version", VERSION)
    root.setdefault("events", [])
    root.setdefault("guild_stats", {})
    if not isinstance(root.get("events"), list):
        root["events"] = []
    if not isinstance(root.get("guild_stats"), dict):
        root["guild_stats"] = {}
    return root


def _command_name(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    name = str(getattr(command, "qualified_name", "") or getattr(command, "name", "") or "unknown")
    return name[:100]


def _source(ctx: commands.Context) -> str:
    if bool(getattr(ctx, "_v1813_button_bridge", False)):
        return "button"
    if getattr(ctx, "interaction", None) is not None:
        return "interaction"
    return "prefix"


def _resolve_guild(bot: commands.Bot, query: str) -> Tuple[Optional[discord.Guild], str]:
    text = str(query or "").strip()
    if not text:
        return None, ""
    if text.isdigit():
        guild = bot.get_guild(int(text))
        return guild, "" if guild is not None else "해당 서버 ID를 찾지 못했습니다."
    lowered = text.casefold()
    exact = [guild for guild in bot.guilds if guild.name.casefold() == lowered]
    if len(exact) == 1:
        return exact[0], ""
    partial = [guild for guild in bot.guilds if lowered in guild.name.casefold()]
    if len(partial) == 1:
        return partial[0], ""
    if len(partial) > 1:
        names = ", ".join(f"{g.name}({g.id})" for g in partial[:6])
        return None, f"같은 이름 후보가 여러 개입니다: {names}"
    return None, "해당 서버 이름을 찾지 못했습니다."


def register_v1815_owner_usage_audit(
    bot: commands.Bot,
    world_data: MutableMapping[str, Any],
    save_data: Callable[[], None],
) -> None:
    if getattr(bot, "_abaddon_v1815_registered", False):
        return

    root = _legacy_root(world_data)
    bot.abaddon_version = VERSION
    pending: Dict[int, Dict[str, Any]] = {}
    fallback_dirty = 0
    storage_mode = "json-fallback"
    migration: Dict[str, Any] = {"migrated": False, "events": 0, "guilds": 0}

    try:
        initialize_sqlite()
        migration = migrate_legacy_usage(root)
        storage_mode = "sqlite"
        had_legacy_payload = bool(root.get("events")) or bool(root.get("guild_stats"))
        # Once imported, remove high-churn telemetry from the large world JSON.
        if had_legacy_payload or root.get("storage") != "sqlite":
            root.clear()
            root.update({
                "version": VERSION,
                "storage": "sqlite",
                "migrated_at": int(time.time()),
                "migrated_events": _safe_int(migration.get("events")),
                "migrated_guilds": _safe_int(migration.get("guilds")),
            })
            try:
                save_data()
            except Exception as exc:
                print(f"[ABADDON v{VERSION} usage compact save warning] {type(exc).__name__}: {exc}", flush=True)
    except Exception as exc:
        print(f"[ABADDON v{VERSION} usage SQLite fallback] {type(exc).__name__}: {exc}", flush=True)
        root.setdefault("events", [])
        root.setdefault("guild_stats", {})

    def fallback_persist() -> None:
        nonlocal fallback_dirty
        fallback_dirty += 1
        if fallback_dirty < FALLBACK_SAVE_EVERY:
            return
        fallback_dirty = 0
        try:
            save_data()
        except Exception as exc:
            print(f"[ABADDON v{VERSION} usage fallback save warning] {type(exc).__name__}: {exc}", flush=True)

    def ctx_key(ctx: commands.Context) -> int:
        message = getattr(ctx, "message", None)
        mid = getattr(message, "id", None)
        if mid is not None:
            try:
                return int(mid)
            except (TypeError, ValueError):
                pass
        interaction = getattr(ctx, "interaction", None)
        iid = getattr(interaction, "id", None)
        if iid is not None:
            try:
                return int(iid)
            except (TypeError, ValueError):
                pass
        return id(ctx)

    def should_track(ctx: commands.Context) -> bool:
        guild = getattr(ctx, "guild", None)
        author = getattr(ctx, "author", None)
        command = getattr(ctx, "command", None)
        if guild is None or author is None or command is None or bool(getattr(author, "bot", False)):
            return False
        return _command_name(ctx).split(" ", 1)[0] not in OWNER_COMMANDS

    def fallback_record(event: Mapping[str, Any]) -> None:
        events = root.setdefault("events", [])
        if not isinstance(events, list):
            events = []
            root["events"] = events
        events.append(dict(event))
        if len(events) > EVENT_LIMIT:
            del events[:-EVENT_LIMIT]
        stats_map = root.setdefault("guild_stats", {})
        if not isinstance(stats_map, dict):
            stats_map = {}
            root["guild_stats"] = stats_map
        gid = str(event.get("guild_id"))
        source = str(event.get("source") or "prefix")
        ok = bool(event.get("ok"))
        command = str(event.get("command") or "unknown")
        stats = stats_map.setdefault(gid, {"runs": 0, "success": 0, "failures": 0, "prefix": 0, "button": 0, "interaction": 0, "last_ts": 0.0, "commands": {}})
        stats["runs"] = _safe_int(stats.get("runs")) + 1
        stats["success" if ok else "failures"] = _safe_int(stats.get("success" if ok else "failures")) + 1
        if source in {"prefix", "button", "interaction"}:
            stats[source] = _safe_int(stats.get(source)) + 1
        stats["last_ts"] = _safe_float(event.get("ts"))
        cmd_map = stats.setdefault("commands", {})
        row = cmd_map.setdefault(command, {"runs": 0, "success": 0, "failures": 0, "prefix": 0, "button": 0, "interaction": 0, "last_ts": 0.0})
        row["runs"] = _safe_int(row.get("runs")) + 1
        row["success" if ok else "failures"] = _safe_int(row.get("success" if ok else "failures")) + 1
        if source in {"prefix", "button", "interaction"}:
            row[source] = _safe_int(row.get(source)) + 1
        row["last_ts"] = _safe_float(event.get("ts"))
        fallback_persist()

    def record_final(ctx: commands.Context, ok: bool, error: str = "") -> None:
        if not should_track(ctx):
            return
        key = ctx_key(ctx)
        started = pending.pop(key, {})
        now = time.time()
        guild_id = int(getattr(getattr(ctx, "guild", None), "id", 0) or 0)
        if not guild_id:
            return
        command = _command_name(ctx)
        source = str(started.get("source") or _source(ctx))
        started_at = _safe_float(started.get("ts"), now)
        duration_ms = max(0.0, (now - started_at) * 1000.0)
        event = {
            "ts": round(now, 3), "guild_id": str(guild_id), "command": command,
            "source": source, "ok": bool(ok), "ms": round(duration_ms, 1), "error": str(error or "")[:120],
        }
        if storage_mode == "sqlite":
            try:
                record_usage_event(guild_id, command, source, ok, duration_ms, error, ts=now, event_limit=EVENT_LIMIT)
                return
            except Exception as exc:
                print(f"[ABADDON v{VERSION} usage record fallback] {type(exc).__name__}: {exc}", flush=True)
        fallback_record(event)

    @bot.listen("on_command")
    async def v1815_command_start(ctx: commands.Context) -> None:
        if should_track(ctx):
            pending[ctx_key(ctx)] = {"ts": time.time(), "source": _source(ctx)}

    @bot.listen("on_command_completion")
    async def v1815_command_complete(ctx: commands.Context) -> None:
        record_final(ctx, True)

    @bot.listen("on_command_error")
    async def v1815_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
        if should_track(ctx):
            original = getattr(error, "original", error)
            record_final(ctx, False, type(original).__name__)

    def record_bridge_failure(ctx: commands.Context, error: Any) -> None:
        if should_track(ctx):
            record_final(ctx, False, error if isinstance(error, str) else type(error).__name__)

    setattr(bot, "v1815_record_bridge_failure", record_bridge_failure)
    setattr(bot, "v1815_usage_storage", storage_mode)
    setattr(bot, "v1815_usage_migration", migration)

    def fetch_recent(guild_id: Optional[int] = None, limit: int = 25, since_ts: Optional[float] = None) -> List[Dict[str, Any]]:
        if storage_mode == "sqlite":
            try:
                return recent_usage_events(guild_id=guild_id, limit=limit, since_ts=since_ts)
            except Exception:
                pass
        rows = [dict(x) for x in root.get("events", []) if isinstance(x, Mapping)]
        if guild_id is not None:
            rows = [x for x in rows if str(x.get("guild_id")) == str(guild_id)]
        if since_ts is not None:
            rows = [x for x in rows if _safe_float(x.get("ts")) >= since_ts]
        return rows[-limit:][::-1]

    def fetch_overview() -> List[Dict[str, Any]]:
        if storage_mode == "sqlite":
            try:
                return usage_guild_overview()
            except Exception:
                pass
        stats = root.get("guild_stats", {}) if isinstance(root.get("guild_stats"), Mapping) else {}
        rows = []
        for gid, row in stats.items():
            if isinstance(row, Mapping):
                rows.append({"guild_id": str(gid), **dict(row)})
        return sorted(rows, key=lambda x: _safe_int(x.get("runs")), reverse=True)

    def fetch_detail(guild_id: int) -> Dict[str, Any]:
        if storage_mode == "sqlite":
            try:
                return usage_guild_detail(guild_id, command_limit=15)
            except Exception:
                pass
        stats = root.get("guild_stats", {}) if isinstance(root.get("guild_stats"), Mapping) else {}
        row = stats.get(str(guild_id), {})
        if not isinstance(row, Mapping):
            return {}
        commands_map = row.get("commands", {}) if isinstance(row.get("commands"), Mapping) else {}
        ranked = sorted(commands_map.items(), key=lambda pair: _safe_int(pair[1].get("runs") if isinstance(pair[1], Mapping) else 0), reverse=True)[:15]
        return {**dict(row), "guild_id": str(guild_id), "commands": [{"command": name, **dict(value)} for name, value in ranked if isinstance(value, Mapping)]}

    async def owner_dm(ctx: commands.Context) -> Optional[discord.abc.Messageable]:
        if not await _private_owner(bot, ctx.author):
            return None
        try:
            return await ctx.author.create_dm()
        except Exception:
            try:
                await ctx.send("⚠️ DM을 열 수 없습니다. 봇의 DM을 허용한 뒤 다시 실행해주세요.")
            except Exception:
                pass
            return None

    @bot.command(name="서버사용로그", aliases=["서버기능로그", "guildusage", "serverusage"], hidden=True, help="[봇 소유자 전용] 서버별 최근 기능 사용 기록을 DM으로 확인합니다.")
    async def server_usage_log(ctx: commands.Context, *, 대상: str = "") -> None:
        dm = await owner_dm(ctx)
        if dm is None:
            return
        guild: Optional[discord.Guild] = None
        if 대상.strip():
            guild, error = _resolve_guild(bot, 대상)
            if guild is None:
                await dm.send(f"❌ {error}\n`!내서버목록`에서 서버 ID를 확인할 수 있습니다.")
                return
        rows = fetch_recent(guild.id if guild else None, 25)
        embed = discord.Embed(title=f"📋 ABADDON 서버 사용 로그 · {guild.name}" if guild else "📋 ABADDON 전체 서버 사용 로그", color=0x7C4DFF)
        embed.description = f"최근 **25건** · 저장소 **{storage_mode}** · 메시지 내용/입력값은 저장하지 않습니다."
        if not rows:
            embed.add_field(name="기록", value="아직 기록된 사용이 없습니다.", inline=False)
        else:
            lines: List[str] = []
            for row in rows:
                gid = _safe_int(row.get("guild_id"))
                source = str(row.get("source") or "prefix")
                source_label = {"button": "버튼", "interaction": "UI", "prefix": "직접"}.get(source, source)
                guild_obj = bot.get_guild(gid)
                guild_name = guild_obj.name if guild_obj is not None else str(gid)
                ok = "✅" if row.get("ok") else "❌"
                error_text = f" · `{str(row.get('error'))[:30]}`" if not row.get("ok") and row.get("error") else ""
                lines.append(f"{ok} <t:{int(_safe_float(row.get('ts')))}:R> · **{guild_name[:28]}** · `!{str(row.get('command') or 'unknown')}` · {source_label}{error_text}")
            for index, title in ((0, "최근 실행"), (10, "이전 기록"), (20, "더 이전")):
                chunk = lines[index:index + 10 if index < 20 else 25]
                if chunk:
                    embed.add_field(name=title, value="\n".join(chunk)[:1024], inline=False)
        embed.set_footer(text=f"보관 한도 {EVENT_LIMIT:,}건 · !서버사용통계 [서버ID/이름]")
        await dm.send(embed=embed)
        if ctx.guild is not None:
            try:
                await ctx.message.add_reaction("✅")
            except Exception:
                pass

    @bot.command(name="서버사용통계", aliases=["서버기능통계", "guildstats", "serverstats"], hidden=True, help="[봇 소유자 전용] 서버별 누적 기능 사용 통계를 DM으로 확인합니다.")
    async def server_usage_stats(ctx: commands.Context, *, 대상: str = "") -> None:
        dm = await owner_dm(ctx)
        if dm is None:
            return
        guild: Optional[discord.Guild] = None
        if 대상.strip():
            guild, error = _resolve_guild(bot, 대상)
            if guild is None:
                await dm.send(f"❌ {error}\n`!내서버목록`에서 서버 ID를 확인할 수 있습니다.")
                return
        if guild is None:
            rows = fetch_overview()
            total_runs = sum(_safe_int(row.get("runs")) for row in rows)
            total_fail = sum(_safe_int(row.get("failures")) for row in rows)
            embed = discord.Embed(title="📊 ABADDON 서버별 사용 통계", color=0x2ECC71)
            embed.description = f"누적 **{total_runs:,}회** · 실패 **{total_fail:,}회** · 기록 서버 **{len(rows)}개** · `{storage_mode}`"
            lines = []
            for row in rows[:15]:
                gid = _safe_int(row.get("guild_id"))
                guild_obj = bot.get_guild(gid)
                name = guild_obj.name if guild_obj else str(gid)
                lines.append(f"• **{name[:30]}** · {_safe_int(row.get('runs')):,}회 · 버튼 {_safe_int(row.get('button')):,} · 실패 {_safe_int(row.get('failures')):,} · `{gid}`")
            embed.add_field(name="서버 TOP", value="\n".join(lines) or "아직 기록이 없습니다.", inline=False)
            embed.set_footer(text="상세: !서버사용통계 서버ID · 최근 기록: !서버사용로그")
            await dm.send(embed=embed)
            return
        row = fetch_detail(guild.id)
        runs = _safe_int(row.get("runs"))
        if runs <= 0:
            await dm.send(f"📭 **{guild.name}** 서버에는 아직 기록된 사용이 없습니다.")
            return
        cutoff = time.time() - 86400
        last_24h = fetch_recent(guild.id, EVENT_LIMIT, cutoff)
        success, failures = _safe_int(row.get("success")), _safe_int(row.get("failures"))
        embed = discord.Embed(title=f"📊 {guild.name} 사용 통계", color=0x2ECC71 if failures == 0 else 0xF1C40F)
        embed.description = f"서버 ID `{guild.id}` · `{storage_mode}` 누적 통계"
        embed.add_field(name="전체 실행", value=f"**{runs:,}회**\n최근 24시간 **{len(last_24h):,}회**", inline=True)
        embed.add_field(name="성공 / 실패", value=f"✅ {success:,}\n❌ {failures:,} ({(failures / runs * 100 if runs else 0):.1f}%)", inline=True)
        embed.add_field(name="실행 방식", value=f"직접 {_safe_int(row.get('prefix')):,}\n버튼 {_safe_int(row.get('button')):,}\n기타 UI {_safe_int(row.get('interaction')):,}", inline=True)
        lines = []
        for cmd_row in row.get("commands", []) if isinstance(row.get("commands"), list) else []:
            lines.append(f"• `!{cmd_row.get('command')}` **{_safe_int(cmd_row.get('runs')):,}회** · 버튼 {_safe_int(cmd_row.get('button')):,} · 실패 {_safe_int(cmd_row.get('failures')):,}")
        embed.add_field(name="많이 확인한 기능 TOP 15", value="\n".join(lines)[:1024] or "기록 없음", inline=False)
        last_ts = int(_safe_float(row.get("last_ts")))
        if last_ts:
            embed.add_field(name="마지막 사용", value=f"<t:{last_ts}:f> · <t:{last_ts}:R>", inline=False)
        embed.set_footer(text="최근 개별 기록: !서버사용로그 서버ID")
        await dm.send(embed=embed)
        if ctx.guild is not None:
            try:
                await ctx.message.add_reaction("✅")
            except Exception:
                pass

    @bot.command(name="1815사용로그검수", aliases=["1815usageaudit"], hidden=True, help="[봇 소유자 전용] 서버 사용 로그 계측 상태를 확인합니다.")
    async def usage_audit(ctx: commands.Context) -> None:
        if not await _private_owner(bot, ctx.author):
            return
        try:
            event_count = usage_event_count() if storage_mode == "sqlite" else len(root.get("events", []))
            sqlite_ok = storage_mode == "sqlite"
        except Exception:
            event_count, sqlite_ok = len(root.get("events", [])), False
        checks = [
            ("서버사용로그 명령", bot.get_command("서버사용로그") is not None),
            ("서버사용통계 명령", bot.get_command("서버사용통계") is not None),
            ("버튼 실패 브리지", callable(getattr(bot, "v1815_record_bridge_failure", None))),
            ("SQLite 전용 사용로그", sqlite_ok),
            ("메시지/입력값 미수집", True),
        ]
        text = "\n".join(f"{'✅' if ok else '❌'} {label}" for label, ok in checks)
        await ctx.send(f"🧪 **ABADDON v{VERSION} 서버 사용 로그 검수**\n{text}\n보관 이벤트: **{event_count:,}건** · 저장소 `{storage_mode}`")

    bot._abaddon_v1815_registered = True
    print(f"[ABADDON v{VERSION}] owner usage audit registered: storage={storage_mode} events={EVENT_LIMIT}", flush=True)
