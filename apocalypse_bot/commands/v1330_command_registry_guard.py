from __future__ import annotations

import inspect
import types
from typing import Any, Dict, List, Mapping

import discord
from discord.ext import commands

VERSION = "13.3.0"
PATCH_DATE = "2026-08-05"


def _command_source(command: commands.Command) -> Dict[str, Any]:
    callback = getattr(command, "callback", None)
    module = str(getattr(callback, "__module__", "") or "")
    try:
        line = int(inspect.getsourcelines(callback)[1]) if callback is not None else 0
    except (OSError, TypeError):
        line = 0
    return {
        "command": str(getattr(command, "qualified_name", getattr(command, "name", ""))),
        "module": module,
        "line": line,
    }


def install_command_registry_guard(bot: commands.Bot) -> None:
    """Install before extension registration so one bad alias cannot stop boot.

    Existing names always win. A new command keeps registering after only the
    conflicting aliases are removed. A duplicate command name is quarantined
    and recorded instead of crashing the whole process.
    """
    if getattr(bot, "_v1330_registry_guard_installed", False):
        return

    original_add_command = bot.add_command
    conflicts: List[Dict[str, Any]] = []
    quarantined: List[Dict[str, Any]] = []

    def guarded_add_command(self: commands.Bot, command: commands.Command, /) -> None:
        registry = self.all_commands if getattr(command, "parent", None) is None else command.parent.all_commands
        source = _command_source(command)
        name = str(command.name)
        existing_name = registry.get(name)
        if existing_name is not None and existing_name is not command:
            row = {
                **source,
                "kind": "command-name",
                "token": name,
                "existing": str(getattr(existing_name, "qualified_name", existing_name.name)),
                "action": "quarantined",
            }
            conflicts.append(row)
            quarantined.append(row)
            print(
                f"[ABADDON v{VERSION}] COMMAND REGISTRY GUARD quarantined command="
                f"{source['command']} token={name} existing={row['existing']} "
                f"source={source['module']}:{source['line']}"
            )
            return None

        clean_aliases: List[str] = []
        seen = {name}
        for raw_alias in list(getattr(command, "aliases", []) or []):
            alias = str(raw_alias)
            if not alias or alias in seen:
                continue
            seen.add(alias)
            existing = registry.get(alias)
            if existing is not None and existing is not command:
                row = {
                    **source,
                    "kind": "alias",
                    "token": alias,
                    "existing": str(getattr(existing, "qualified_name", existing.name)),
                    "action": "alias-removed",
                }
                conflicts.append(row)
                print(
                    f"[ABADDON v{VERSION}] COMMAND REGISTRY GUARD removed alias="
                    f"{alias} new={source['command']} existing={row['existing']} "
                    f"source={source['module']}:{source['line']}"
                )
                continue
            clean_aliases.append(alias)
        command.aliases = clean_aliases

        try:
            return original_add_command(command)
        except commands.CommandRegistrationError as exc:
            row = {
                **source,
                "kind": "registration-error",
                "token": str(getattr(exc, "name", "") or name),
                "existing": "unknown",
                "action": "quarantined",
                "error": f"{type(exc).__name__}: {exc}",
            }
            conflicts.append(row)
            quarantined.append(row)
            print(
                f"[ABADDON v{VERSION}] COMMAND REGISTRY GUARD caught {row['error']} "
                f"source={source['module']}:{source['line']}"
            )
            return None

    bot.add_command = types.MethodType(guarded_add_command, bot)
    bot._v1330_registry_guard_installed = True
    bot._v1330_original_add_command = original_add_command
    bot.v1330_command_conflicts = conflicts
    bot.v1330_quarantined_commands = quarantined
    print(f"[ABADDON v{VERSION}] command registration guard installed")


def _registry_snapshot(bot: commands.Bot) -> Dict[str, Any]:
    commands_seen = list(bot.walk_commands())
    tokens: Dict[str, List[str]] = {}
    for command in commands_seen:
        for token in [str(command.name), *[str(item) for item in command.aliases]]:
            tokens.setdefault(token, []).append(str(command.qualified_name))
    duplicates = {
        token: sorted(set(owners))
        for token, owners in tokens.items()
        if len(set(owners)) > 1
    }
    return {
        "commands": len(commands_seen),
        "tokens": len(tokens),
        "duplicates": duplicates,
        "runtime_conflicts": list(getattr(bot, "v1330_command_conflicts", [])),
        "quarantined": list(getattr(bot, "v1330_quarantined_commands", [])),
    }


def register_v1330_command_registry_guard(
    bot: commands.Bot,
    guide: List[Dict[str, Any]],
) -> None:
    install_command_registry_guard(bot)

    @bot.command(
        name="명령등록검수",
        aliases=["commandregistryaudit", "registrationaudit"],
        help="명령어 이름·별칭 충돌과 격리 내역을 확인합니다.",
    )
    async def command_registry_audit(ctx: commands.Context, mode: str = "") -> None:
        report = _registry_snapshot(bot)
        conflicts = report["runtime_conflicts"]
        duplicates = report["duplicates"]
        detailed = str(mode).strip().lower() in {"상세", "detail", "detailed", "full"}
        embed = discord.Embed(
            title="🛡️ ABADDON 명령 등록 검수",
            description=(
                f"등록 명령 **{report['commands']:,}개** · 접근 이름 **{report['tokens']:,}개**\n"
                f"부팅 중 충돌 제거 **{len(conflicts)}건** · 격리 **{len(report['quarantined'])}건** · 현재 중복 **{len(duplicates)}건**"
            ),
            color=0x3BA55D if not duplicates and not report["quarantined"] else 0xF0B232,
        )
        if detailed and conflicts:
            lines = []
            for row in conflicts[-15:]:
                lines.append(
                    f"`{row.get('token')}` · {row.get('action')} · "
                    f"{row.get('command')} ↔ {row.get('existing')} · "
                    f"{row.get('module')}:{row.get('line')}"
                )
            embed.add_field(name="최근 충돌 처리", value="\n".join(lines)[:1024], inline=False)
        if duplicates:
            lines = [f"`{token}` → {', '.join(owners)}" for token, owners in list(duplicates.items())[:12]]
            embed.add_field(name="현재 중복", value="\n".join(lines)[:1024], inline=False)
        embed.set_footer(text=f"ABADDON v{VERSION} · 기존 명령 우선 · 충돌 별칭만 제거")
        await ctx.send(embed=embed)

    @bot.command(
        name="1330안정화검수",
        aliases=["v1330audit", "1330audit"],
        help="v13.3.0 부팅 안정화 패치 상태를 확인합니다.",
    )
    async def v1330_audit(ctx: commands.Context, mode: str = "") -> None:
        report = _registry_snapshot(bot)
        detailed = str(mode).strip().lower() in {"상세", "detail", "detailed", "full"}
        checks = [
            ("명령 등록 보호기", bool(getattr(bot, "_v1330_registry_guard_installed", False))),
            ("현재 접근 이름 중복 없음", not report["duplicates"]),
            ("영문 별칭 최종 동기화", hasattr(bot, "v950_english_sync")),
            ("부팅 중 오류 격리 기록", hasattr(bot, "v1330_command_conflicts")),
        ]
        passed = sum(1 for _, ok in checks if ok)
        lines = [f"{'✅' if ok else '❌'} {label}" for label, ok in checks]
        if detailed:
            lines.append(f"• 처리된 충돌: {len(report['runtime_conflicts'])}건")
            lines.append(f"• 격리된 명령: {len(report['quarantined'])}건")
            lines.append(f"• 등록 명령: {report['commands']:,}개")
        await ctx.send(
            f"🧪 **ABADDON v{VERSION} 안정화 검수** · {passed}/{len(checks)} 통과\n" + "\n".join(lines)
        )

    patch = bot.get_command("패치노트")
    if patch is not None:
        previous = patch.callback

        async def v1330_patch_notes(ctx: commands.Context, *args: Any, **kwargs: Any) -> None:
            embed = discord.Embed(
                title="🛡️ ABADDON v13.3.0 — 명령 등록 충돌 긴급 패치",
                description=(
                    "`expedition` 별칭이 기존 `원정` 명령과 충돌해 부팅이 중단되던 문제를 수정했습니다. "
                    "앞으로는 별칭 한 개가 충돌해도 봇 전체가 종료되지 않고, 기존 명령을 보존한 채 충돌 별칭만 제거합니다."
                ),
                color=0x5865F2,
            )
            embed.add_field(
                name="수정된 충돌",
                value="`expedition` · `fortune` · `checkin` · `marketbuy`를 신규 기능 전용 고유 별칭으로 분리했습니다.",
                inline=False,
            )
            embed.add_field(
                name="진단",
                value="`!명령등록검수 상세` · `!1330안정화검수 상세`",
                inline=False,
            )
            embed.set_footer(text=f"Patch {PATCH_DATE} · BLACK CITY 기능과 저장 데이터 변경 없음")
            await ctx.send(embed=embed)

        patch.callback = v1330_patch_notes
        patch.help = "ABADDON v13.3.0 명령 등록 충돌 긴급 패치를 확인합니다."
        patch.description = patch.help
        patch.extras = dict(getattr(patch, "extras", {}) or {})
        patch.extras["v1330_previous_callback"] = previous

    guide.append({
        "id": "v1330_runtime_stability",
        "emoji": "🛡️",
        "title": "명령 등록 안정화",
        "hint": "부팅 충돌과 격리 내역을 검사합니다.",
        "commands": [
            "!명령등록검수 / !명령등록검수 상세",
            "!1330안정화검수 / !1330안정화검수 상세",
        ],
    })

    bot.v1330_version = VERSION
    bot.v1330_registry_snapshot = lambda: _registry_snapshot(bot)
    print(f"[ABADDON v{VERSION}] command registry diagnostics registered")
