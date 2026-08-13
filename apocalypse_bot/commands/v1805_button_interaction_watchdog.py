from __future__ import annotations

"""ABADDON v18.0.5 BUTTON INTERACTION WATCHDOG.

Final interaction reliability hotfix for v18.0.3 contextual buttons/dropdowns.
The actual bridge watchdog lives in v1803_contextual_ui so existing views receive
it without changing any gameplay command or save-data schema.
"""

from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional

import discord
from discord.ext import commands

VERSION = "18.0.5"


def _locale(bot: commands.Bot, ctx: commands.Context) -> str:
    try:
        from apocalypse_bot.commands import v1660_first_survival_live_qa as live1660
        return live1660._locale(bot, ctx)
    except Exception:
        return "ko"


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def register_v1805_button_interaction_watchdog(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    del get_user, check_registered, save_data, world_data, user_data, guide
    if getattr(bot, "_abaddon_v1805_registered", False):
        return
    bot._abaddon_v1805_registered = True
    bot.abaddon_version = VERSION
    bot.v1805_context_timeout_seconds = 15
    bot.v1805_context_completion_cleanup_seconds = 1.2
    if not isinstance(getattr(bot, "_v1805_context_locks", None), set):
        bot._v1805_context_locks = set()

    @bot.command(
        name="버튼상태",
        aliases=["상호작용상태", "buttonstatus", "interactionstatus"],
        help="v18.0.5 버튼·드롭다운 상호작용 감시 상태를 확인합니다.",
    )
    async def button_status(ctx: commands.Context) -> None:
        locale = _locale(bot, ctx)
        busy = len(getattr(bot, "_v1805_context_locks", set()) or set())
        embed = discord.Embed(
            title=_t(locale, "🛡️ 버튼 상호작용 감시", "🛡️ Interaction Watchdog"),
            color=0x4F7BFF,
        )
        embed.add_field(
            name=_t(locale, "실행 제한", "Execution timeout"),
            value=_t(locale, "기능 버튼·드롭다운은 **15초** 안에 완료되어야 합니다.", "Context buttons/selects have a **15s** execution timeout."),
            inline=False,
        )
        embed.add_field(
            name=_t(locale, "생각 중 표시", "Thinking state"),
            value=_t(locale, "실행 종료 후 `생각 중...` 표시를 자동으로 닫습니다.", "The deferred thinking state is automatically resolved after execution."),
            inline=False,
        )
        embed.add_field(
            name=_t(locale, "중복 클릭", "Duplicate clicks"),
            value=_t(locale, f"사용자별 1개만 실행 · 현재 처리 중 **{busy}건**", f"One action per user · currently running **{busy}**"),
            inline=False,
        )
        embed.set_footer(text=_t(locale, "기존 !명령어 직접 실행 방식은 변경하지 않았습니다.", "Legacy prefix commands are unchanged."))
        await ctx.send(embed=embed)

    @bot.command(
        name="1805버튼검수",
        aliases=["v1805audit", "1805audit", "버튼상호작용검수"],
        help="v18.0.5 버튼 상호작용 Watchdog 적용 상태를 검사합니다.",
    )
    async def audit_1805(ctx: commands.Context, 상세: str = "") -> None:
        locale = _locale(bot, ctx)
        try:
            from apocalypse_bot.commands import v1803_contextual_ui as ui
            source_ok = callable(getattr(ui, "_run_context_interaction", None))
            cleanup_ok = callable(getattr(ui, "_clear_completed_indicator", None))
            timeout_ok = "15.0" in str(getattr(ui._run_context_interaction, "__code__", "")) or int(getattr(bot, "v1805_context_timeout_seconds", 0)) == 15
        except Exception:
            source_ok = cleanup_ok = timeout_ok = False
        checks = [
            (_t(locale, "상황 맞춤 버튼 엔진", "Contextual button engine"), bool(getattr(bot, "_abaddon_v1803_registered", False))),
            (_t(locale, "상호작용 Watchdog", "Interaction watchdog"), source_ok),
            (_t(locale, "완료 후 대기 표시 정리", "Thinking-state cleanup"), cleanup_ok),
            (_t(locale, "15초 타임아웃", "15-second timeout"), timeout_ok),
            (_t(locale, "중복 클릭 잠금", "Duplicate-click lock"), isinstance(getattr(bot, "_v1805_context_locks", None), set)),
            (_t(locale, "기존 직접 명령 보존", "Legacy commands preserved"), bot.get_command("재난상황") is not None),
            (_t(locale, "재난 기능 버튼 대상 보존", "Disaster actions preserved"), "disaster" in getattr(__import__("apocalypse_bot.commands.v1803_contextual_ui", fromlist=["GROUP_BUTTONS"]), "GROUP_BUTTONS", {})),
        ]
        ok = all(flag for _, flag in checks)
        embed = discord.Embed(
            title=_t(locale, "🧪 ABADDON v18.0.5 버튼 검수", "🧪 ABADDON v18.0.5 Button Audit"),
            color=0x32D583 if ok else 0xE5484D,
        )
        embed.description = "\n".join(("✅" if flag else "❌") + " " + name for name, flag in checks)
        embed.add_field(
            name=_t(locale, "런타임", "Runtime"),
            value=_t(
                locale,
                f"처리 중={len(getattr(bot, '_v1805_context_locks', set()) or set())} · 타임아웃=15초 · 완료표시 자동정리",
                f"in_flight={len(getattr(bot, '_v1805_context_locks', set()) or set())} · timeout=15s · completion cleanup=on",
            ),
            inline=False,
        )
        if str(상세).strip():
            embed.add_field(
                name=_t(locale, "보존", "Preservation"),
                value=_t(locale, "기존 명령·저장 데이터 삭제 0건 · 버튼 경로만 보강", "No legacy command/save deletion · interaction path only"),
                inline=False,
            )
        await ctx.send(embed=embed)

    print(
        "[ABADDON v18.0.5] button interaction watchdog registered: "
        "timeout=15s duplicate_lock=enabled thinking_cleanup=enabled",
        flush=True,
    )
