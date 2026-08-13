from __future__ import annotations

"""ABADDON v16.7.1 command-center runtime hotfix.

Fixes the v16.7.0 regression where the rebuilt command center referenced
_safe_select_options / _safe_embed / _safe_view without importing them.
This module adds runtime checks and refreshes latest patch/test surfaces.
"""

from pathlib import Path
from typing import Any, Callable, MutableMapping, Sequence

import discord
from discord.ext import commands

from apocalypse_bot.commands.v600_game_center import _safe_embed
from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as hub

VERSION = "16.7.1"


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _locale(ctx: commands.Context) -> str:
    try:
        from apocalypse_bot.commands import v1000_global_survivor as global_mod
        root = global_mod._RUNTIME.get("root", {})
        return global_mod._user_locale(root, int(ctx.author.id), int(ctx.guild.id if ctx.guild else 0))
    except Exception:
        return "ko"


def _helper_checks() -> dict[str, bool]:
    return {
        "_safe_select_options": callable(getattr(hub, "_safe_select_options", None)),
        "_safe_embed": callable(getattr(hub, "_safe_embed", None)),
        "_safe_view": callable(getattr(hub, "_safe_view", None)),
        "CompleteCommandCenterView": callable(getattr(hub, "CompleteCommandCenterView", None)),
        "기능군 선택 메뉴": callable(getattr(hub, "GroupSelect", None)),
        "세부 명령 선택 메뉴": callable(getattr(hub, "CommandSelect", None)),
    }


def register_v1671_command_center_nameerror_hotfix(
    bot: commands.Bot,
    get_user: Callable[..., Any],
    check_registered: Callable[..., Any],
    save_data: Callable[..., Any],
    world_data: MutableMapping[str, Any],
    user_data: MutableMapping[str, Any],
    guide: list[dict[str, Any]],
) -> None:
    del get_user, check_registered, save_data, world_data, user_data
    bot.abaddon_version = VERSION

    @bot.command(
        name="1671통합검수",
        aliases=["v1671audit", "1671audit", "명령어긴급검수", "commandcenterhotfixaudit"],
        help="v16.7.1 명령어 센터 안전 함수 연결과 한·영 메뉴 재구성을 검사합니다.",
    )
    async def v1671_audit(ctx: commands.Context, mode: str = "") -> None:
        locale = _locale(ctx)
        checks = _helper_checks()
        try:
            entries = hub._build_registry(bot)
            checks["실시간 명령 목록 재수집"] = bool(entries)
            checks["한국어 명령 진입점"] = bot.get_command("명령어") is not None
            checks["English help entry"] = bot.get_command("help") is not None
        except Exception:
            checks["실시간 명령 목록 재수집"] = False
        ok = all(checks.values())
        embed = discord.Embed(
            title=_t(locale, f"🩹 ABADDON v{VERSION} 명령어 센터 긴급 검수", f"🩹 ABADDON v{VERSION} Command Center Hotfix Audit"),
            color=0x2ECC71 if ok else 0xE74C3C,
        )
        embed.description = "\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks.items())
        if str(mode or "").casefold() in {"상세", "detail", "full"}:
            embed.add_field(
                name=_t(locale, "수정 내용", "Fix"),
                value=_t(
                    locale,
                    "명령어 센터가 사용하는 선택 옵션·임베드·뷰 안전 함수를 명시적으로 연결했습니다. 재시작 뒤 `!명령어`와 `!help`가 같은 실시간 목록으로 열립니다.",
                    "Explicitly connected the select-option, embed, and view sanitizers used by the command center. After restart, `!help` reloads the same live command registry.",
                ),
                inline=False,
            )
            embed.add_field(
                name=_t(locale, "주의", "Note"),
                value=_t(locale, "오류센터의 과거 사건은 기록으로 남을 수 있습니다. 새 실행 성공 여부를 기준으로 확인하세요.", "Historical incidents may remain visible. Verify using a fresh command-center execution."),
                inline=False,
            )
        await ctx.send(embed=_safe_embed(embed))

    patch = bot.get_command("패치노트")
    if patch is not None:
        previous_patch = patch.callback

        async def patch_notes_v1671(ctx: commands.Context) -> None:
            locale = _locale(ctx)
            embed = discord.Embed(
                title=_t(locale, f"🩹 ABADDON v{VERSION} COMMAND CENTER HOTFIX", f"🩹 ABADDON v{VERSION} COMMAND CENTER HOTFIX"),
                color=0x7137C8,
            )
            embed.add_field(
                name=_t(locale, "📚 `!명령어` NameError 수정", "📚 `!help` NameError Fix"),
                value=_t(locale, "기능군·세부 명령 드롭다운이 호출하던 안전 함수 3종을 명시적으로 연결했습니다.", "Explicitly connected all three sanitizer helpers used by group and command dropdowns."),
                inline=False,
            )
            embed.add_field(
                name=_t(locale, "🧭 실시간 목록 유지", "🧭 Live Registry Preserved"),
                value=_t(locale, "기존 1,300여 개 명령 분류·빠른 버튼·검색·즐겨찾기·한영 분리 구조는 그대로 유지합니다.", "Preserves the full command registry, shortcuts, search, favorites, and locale-separated UI."),
                inline=False,
            )
            embed.add_field(
                name=_t(locale, "🧪 점검", "🧪 Checks"),
                value="`!명령어` · `!help` · `!1671통합검수 상세` · `!실시간오류센터 상세`",
                inline=False,
            )
            embed.set_footer(text=_t(locale, "기존 기능·저장 데이터 삭제 0건", "0 legacy features or save data removed"))
            await ctx.send(embed=_safe_embed(embed))

        patch.callback = patch_notes_v1671
        patch.help = "ABADDON v16.7.1 명령어 센터 NameError 긴급 수정 패치노트입니다."
        patch.description = patch.help
        patch.extras = dict(getattr(patch, "extras", {}) or {})
        patch.extras["v1671_previous_callback"] = previous_patch

    test = bot.get_command("테스트")
    if test is not None:
        previous_test = test.callback

        async def latest_test_v1671(ctx: commands.Context, mode: str = "", *args: Any, **kwargs: Any) -> None:
            del kwargs
            locale = _locale(ctx)
            checks = _helper_checks()
            checks["명령어"] = bot.get_command("명령어") is not None
            checks["help"] = bot.get_command("help") is not None
            checks["1671통합검수"] = bot.get_command("1671통합검수") is not None
            ok = all(checks.values())
            embed = discord.Embed(
                title=_t(locale, f"🧪 ABADDON v{VERSION} 최신 테스트", f"🧪 ABADDON v{VERSION} Latest Test"),
                color=0x2ECC71 if ok else 0xE74C3C,
            )
            embed.description = "\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks.items())
            detail = str(mode or "").casefold() in {"상세", "detail", "full"} or any(str(arg).casefold() in {"상세", "detail", "full"} for arg in args)
            if detail:
                embed.add_field(
                    name=_t(locale, "이번 범위", "Current Scope"),
                    value=_t(locale, "명령어 센터 안전 함수 연결 · 드롭다운 생성 · 한영 진입점 · 실시간 목록 재수집", "Command-center sanitizers · dropdown construction · locale entries · live registry rebuild"),
                    inline=False,
                )
            await ctx.send(embed=_safe_embed(embed))

        test.callback = latest_test_v1671
        test.help = "v16.7.1 명령어 센터 NameError와 드롭다운 안전 함수 연결을 검사합니다."
        test.description = test.help
        test.extras = dict(getattr(test, "extras", {}) or {})
        test.extras["v1671_previous_callback"] = previous_test

    entries = hub._build_registry(bot)
    setattr(bot, "v1630_command_entries", entries)
    setattr(bot, "v1630_command_index", {entry.qualified_name: entry for entry in entries})

    guide.append({
        "id": "v1671_command_center_hotfix",
        "emoji": "🩹",
        "title": "v16.7.1 COMMAND CENTER HOTFIX",
        "hint": "명령어 드롭다운 NameError 수정·안전 함수 연결·실시간 목록 재검수",
        "commands": [
            "!명령어 · !help",
            "!1671통합검수 상세 · !실시간오류센터 상세",
            "!테스트 상세 · !패치노트",
        ],
    })

    print(f"[ABADDON v{VERSION}] command center hotfix registered", flush=True)
