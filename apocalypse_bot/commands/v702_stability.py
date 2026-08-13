from __future__ import annotations

import os
import datetime as _dt
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import discord
from discord.ext import commands

VERSION = "7.8.0"
ROOT_KEY = "operations_v702"
INCIDENT_LIMIT = 50
COMMAND_LIMIT = 240


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


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


def _root(world_data: Dict[str, Any]) -> Dict[str, Any]:
    root = world_data.setdefault(ROOT_KEY, {})
    if not isinstance(root, dict):
        root = {}
        world_data[ROOT_KEY] = root
    root.setdefault("version", VERSION)
    root.setdefault("boot_count", 0)
    root.setdefault("last_boot_at", "")
    root.setdefault("command_stats", {})
    root.setdefault("incidents", [])
    root.setdefault("last_manual_backup", {})
    if not isinstance(root.get("command_stats"), dict):
        root["command_stats"] = {}
    if not isinstance(root.get("incidents"), list):
        root["incidents"] = []
    root["version"] = VERSION
    return root


def _command_name(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    return str(getattr(command, "qualified_name", "") or getattr(command, "name", "") or "unknown")[:100]


def _format_bytes(size: Any) -> str:
    value = max(0, _safe_int(size))
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value / (1024 * 1024):.2f} MB"


def _short_path(value: Any) -> str:
    text = str(value or "-")
    return text if len(text) <= 72 else "…" + text[-71:]


def register_v702_stability(
    bot: commands.Bot,
    world_data: Dict[str, Any],
    user_data: Dict[str, Any],
    save_data: Callable[[], None],
    *,
    data_file: str,
    create_backup: Callable[[str], Mapping[str, Any]],
    list_backups: Callable[[], List[Dict[str, Any]]],
    validate_snapshot: Callable[[str], Dict[str, Any]],
    runtime_state: Optional[Callable[[], Dict[str, Any]]] = None,
) -> None:
    if getattr(bot, "_abaddon_v702_registered", False):
        return
    bot._abaddon_v702_registered = True
    root = _root(world_data)
    root["boot_count"] = _safe_int(root.get("boot_count")) + 1
    root["last_boot_at"] = _now_iso()

    dirty_events = 0

    def trim_stats() -> None:
        stats = root["command_stats"]
        if len(stats) <= COMMAND_LIMIT:
            return
        ranked = sorted(
            stats.items(),
            key=lambda pair: (_safe_int(pair[1].get("runs")), str(pair[1].get("last_at", ""))),
            reverse=True,
        )[:COMMAND_LIMIT]
        root["command_stats"] = dict(ranked)

    def stat_row(name: str) -> Dict[str, Any]:
        stats = root["command_stats"]
        row = stats.setdefault(name, {})
        if not isinstance(row, dict):
            row = {}
            stats[name] = row
        row.setdefault("runs", 0)
        row.setdefault("success", 0)
        row.setdefault("failures", 0)
        row.setdefault("total_seconds", 0.0)
        row.setdefault("last_at", "")
        row.setdefault("last_error", "")
        return row

    def mark_dirty() -> None:
        nonlocal dirty_events
        dirty_events += 1
        # 정상 명령 25회마다 운영 통계를 함께 영속화합니다.
        if dirty_events >= 25:
            dirty_events = 0
            try:
                save_data()
            except Exception as exc:
                print(f"[V7.0.2 운영 통계 저장 경고] {type(exc).__name__}: {exc}", flush=True)

    def record_start(ctx: commands.Context) -> None:
        row = stat_row(_command_name(ctx))
        row["runs"] = _safe_int(row.get("runs")) + 1
        row["last_at"] = _now_iso()
        trim_stats()

    def record_success(ctx: commands.Context, seconds: float) -> None:
        row = stat_row(_command_name(ctx))
        row["success"] = _safe_int(row.get("success")) + 1
        row["total_seconds"] = round(_safe_float(row.get("total_seconds")) + max(0.0, float(seconds)), 4)
        row["last_at"] = _now_iso()
        mark_dirty()

    def record_failure(ctx: commands.Context, error: BaseException, incident_id: str, seconds: float) -> None:
        name = _command_name(ctx)
        row = stat_row(name)
        row["failures"] = _safe_int(row.get("failures")) + 1
        row["total_seconds"] = round(_safe_float(row.get("total_seconds")) + max(0.0, float(seconds)), 4)
        row["last_at"] = _now_iso()
        row["last_error"] = f"{type(error).__name__}: {error}"[:300]
        incidents = root["incidents"]
        incidents.insert(0, {
            "id": str(incident_id),
            "at": _now_iso(),
            "command": name,
            "error_type": type(error).__name__,
            "message": str(error)[:300],
            "user_id": str(getattr(getattr(ctx, "author", None), "id", "")),
            "guild_id": str(getattr(getattr(ctx, "guild", None), "id", "")),
        })
        del incidents[INCIDENT_LIMIT:]
        mark_dirty()

    bot.v702_record_command_start = record_start
    bot.v702_record_command_success = record_success
    bot.v702_record_command_failure = record_failure
    bot.abaddon_version = VERSION

    async def require_admin(ctx: commands.Context) -> bool:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("❌ 서버 안에서만 사용할 수 있습니다.")
            return False
        perms = ctx.author.guild_permissions
        if not (perms.administrator or perms.manage_guild):
            await ctx.send("❌ 서버 관리자만 사용할 수 있습니다.")
            return False
        return True

    def current_runtime() -> Dict[str, Any]:
        if callable(runtime_state):
            try:
                value = runtime_state()
                return value if isinstance(value, dict) else {}
            except Exception as exc:
                return {"error": f"{type(exc).__name__}: {exc}"}
        return {}

    def failure_rows() -> List[tuple[str, Dict[str, Any]]]:
        return sorted(
            root["command_stats"].items(),
            key=lambda pair: (_safe_int(pair[1].get("failures")), _safe_int(pair[1].get("runs"))),
            reverse=True,
        )

    @bot.command(name="시스템점검", aliases=["운영점검", "systemcheck"])
    async def system_check(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        state = validate_snapshot(data_file)
        backups = list_backups()
        valid_backups = [row for row in backups if row.get("valid")]
        runtime = current_runtime()
        recovery = getattr(bot, "_abaddon_load_recovery_status", {})
        incidents = root["incidents"]
        total_runs = sum(_safe_int(row.get("runs")) for row in root["command_stats"].values())
        total_failures = sum(_safe_int(row.get("failures")) for row in root["command_stats"].values())
        fail_rate = total_failures / max(1, total_runs) * 100
        color = discord.Color.green() if state.get("valid") and valid_backups else discord.Color.orange()
        embed = discord.Embed(
            title=f"🛡️ ABADDON v{getattr(bot, 'abaddon_version', VERSION)} 운영 점검",
            description="데이터·백업·복구·명령 처리 상태를 한 화면에서 확인합니다.",
            color=color,
        )
        embed.add_field(
            name="💾 주 데이터",
            value=(
                f"상태 **{'정상' if state.get('valid') else '점검 필요'}**\n"
                f"크기 **{_format_bytes(state.get('size'))}** · 생존자 **{state.get('users', 0):,}명**\n"
                f"`{_short_path(data_file)}`"
            ),
            inline=False,
        )
        latest = valid_backups[0] if valid_backups else {}
        embed.add_field(
            name="🗄️ 회전 백업",
            value=(
                f"정상 **{len(valid_backups)}개** / 전체 {len(backups)}개\n"
                f"최근 `{latest.get('name', '없음')}`\n"
                f"저장 횟수 **{runtime.get('save_count', '-')}회**"
            ),
            inline=True,
        )
        embed.add_field(
            name="♻️ 시작 복구",
            value=(
                f"복구 실행 **{'예' if recovery.get('recovered') else '아니오'}**\n"
                f"출처 `{_short_path(recovery.get('source', '확인 전'))}`"
            ),
            inline=True,
        )
        embed.add_field(
            name="📊 명령 처리",
            value=f"실행 **{total_runs:,}회** · 실패 **{total_failures:,}회**\n실패율 **{fail_rate:.2f}%** · 사건 {len(incidents)}건 보관",
            inline=True,
        )
        if runtime.get("last_save_error"):
            embed.add_field(name="⚠️ 최근 저장 오류", value=str(runtime["last_save_error"])[:900], inline=False)
        embed.set_footer(text="상세 오류: !오류현황 · 백업: !백업목록 · 즉시 백업: !백업생성")
        await ctx.send(embed=embed)

    @bot.command(name="오류현황", aliases=["사건현황", "errorstatus"])
    async def error_status(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        ranked = [item for item in failure_rows() if _safe_int(item[1].get("failures")) > 0][:8]
        lines = []
        for name, row in ranked:
            runs = _safe_int(row.get("runs"))
            failures = _safe_int(row.get("failures"))
            lines.append(f"• `!{name}` 실패 **{failures}회** / 실행 {runs}회 · {str(row.get('last_error') or '-')[:90]}")
        incident_lines = []
        for item in root["incidents"][:8]:
            incident_lines.append(
                f"• `{item.get('id', '-')}` · `!{item.get('command', '?')}` · {item.get('error_type', 'Error')} · 길드 `{item.get('guild_id') or '-'}`"
            )
        embed = discord.Embed(title="🚨 최근 오류·사건 현황", color=discord.Color.red())
        embed.add_field(name="실패가 많은 명령", value="\n".join(lines) or "기록된 실패가 없습니다.", inline=False)
        embed.add_field(name="최근 사건 번호", value="\n".join(incident_lines) or "기록된 사건이 없습니다.", inline=False)
        embed.set_footer(text=f"최근 사건 최대 {INCIDENT_LIMIT}건을 보관합니다.")
        await ctx.send(embed=embed)

    @bot.command(name="운영통계", aliases=["명령통계", "commandstats"], hidden=True, help="[봇 소유자 전용] 전체 봇 명령 운영 통계를 확인합니다.")
    async def command_stats(ctx: commands.Context) -> None:
        from apocalypse_bot.commands.v1811_presence_owner_servers import _private_owner
        if not await _private_owner(bot, ctx.author):
            await ctx.send("🔒 이 통계는 봇 소유자만 확인할 수 있습니다.")
            return
        ranked = sorted(
            root["command_stats"].items(),
            key=lambda pair: _safe_int(pair[1].get("runs")),
            reverse=True,
        )[:12]
        lines = []
        for name, row in ranked:
            runs = _safe_int(row.get("runs"))
            success = _safe_int(row.get("success"))
            failures = _safe_int(row.get("failures"))
            avg = _safe_float(row.get("total_seconds")) / max(1, success + failures)
            lines.append(f"• `!{name}` **{runs}회** · 성공 {success} / 실패 {failures} · 평균 {avg:.2f}초")
        await ctx.send("📈 **[명령어 운영 통계]**\n" + ("\n".join(lines) if lines else "아직 기록이 없습니다."))

    @bot.command(name="백업목록", aliases=["데이터백업목록", "backuplist"])
    async def backup_list(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        rows = list_backups()
        if not rows:
            await ctx.send("📭 생성된 회전 백업이 없습니다. `!백업생성`을 실행하세요.")
            return
        lines = []
        for row in rows[:15]:
            icon = "✅" if row.get("valid") else "❌"
            lines.append(
                f"{icon} `{row.get('name', '-')}` · {_format_bytes(row.get('size'))} · 사용자 {row.get('users', 0):,}명"
            )
        await ctx.send("🗄️ **[데이터 백업 목록]**\n" + "\n".join(lines))

    @bot.command(name="백업생성", aliases=["즉시백업", "backupnow"])
    @commands.cooldown(1, 30.0, commands.BucketType.guild)
    async def backup_now(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        try:
            save_data()
            result = dict(create_backup("manual"))
            root["last_manual_backup"] = {
                "name": result.get("name", ""),
                "at": _now_iso(),
                "admin_id": str(ctx.author.id),
            }
            save_data()
        except Exception as exc:
            await ctx.send(f"❌ 백업 생성 실패: `{type(exc).__name__}: {str(exc)[:300]}`")
            return
        await ctx.send(
            "✅ **검증된 수동 백업을 생성했습니다.**\n"
            f"파일: `{result.get('name', '-')}`\n"
            f"크기: **{_format_bytes(result.get('size'))}** · 생존자 **{result.get('users', 0):,}명**"
        )

    @bot.command(name="백업검증", aliases=["데이터검증", "backupcheck"])
    async def backup_check(ctx: commands.Context) -> None:
        if not await require_admin(ctx):
            return
        primary = validate_snapshot(data_file)
        backup = validate_snapshot(f"{data_file}.bak")
        snapshots = list_backups()
        valid = sum(1 for row in snapshots if row.get("valid"))
        text = (
            "🔍 **[데이터 무결성 검사]**\n"
            f"• 주 데이터: **{'정상' if primary.get('valid') else '오류'}** · {_format_bytes(primary.get('size'))} · 사용자 {primary.get('users', 0):,}명\n"
            f"• 직전 `.bak`: **{'정상' if backup.get('valid') else '없음/오류'}** · {_format_bytes(backup.get('size'))}\n"
            f"• 회전 백업: **정상 {valid}개 / 전체 {len(snapshots)}개**"
        )
        if not primary.get("valid"):
            text += f"\n⚠️ 주 데이터 오류: `{primary.get('error', '-')}`"
        await ctx.send(text)

    @bot.command(name="복구미리보기", aliases=["백업비교", "restorepreview"])
    async def restore_preview(ctx: commands.Context, *, 파일명: str = "") -> None:
        if not await require_admin(ctx):
            return
        rows = list_backups()
        valid_rows = [row for row in rows if row.get("valid")]
        if not valid_rows:
            await ctx.send("⚠️ 비교할 정상 회전 백업이 없습니다.")
            return
        target = None
        query = 파일명.strip()
        if query:
            target = next((row for row in valid_rows if row.get("name") == query), None)
            if target is None:
                await ctx.send("⚠️ 해당 백업 파일을 찾지 못했습니다. `!백업목록`에서 정확한 파일명을 확인하세요.")
                return
        else:
            target = valid_rows[0]
        current = validate_snapshot(data_file)
        user_delta = _safe_int(target.get("users")) - _safe_int(current.get("users"))
        size_delta = _safe_int(target.get("size")) - _safe_int(current.get("size"))
        await ctx.send(
            "♻️ **[복구 미리보기 — 실제 복구는 수행하지 않음]**\n"
            f"대상: `{target.get('name', '-')}`\n"
            f"현재 사용자 **{current.get('users', 0):,}명** → 백업 **{target.get('users', 0):,}명** ({user_delta:+,})\n"
            f"현재 크기 **{_format_bytes(current.get('size'))}** → 백업 **{_format_bytes(target.get('size'))}** ({size_delta:+,} B)\n"
            "⚠️ 실제 복구는 Render 서비스를 중지한 뒤 파일을 교체하고 재시작하는 방식으로 진행하세요."
        )
