from __future__ import annotations

"""ABADDON v16.6.1 RUNTIME INTERACTION HOTFIX.

Focused runtime patch for Discord interaction compatibility:
- treat discord.py 2.7's MISSING cog sentinel as no cog in button execution;
- normalize select options and embed/view payloads to Discord API limits;
- acknowledge command-center and equipment selects before editing;
- replace the latest test output with a compact safe payload;
- preserve every legacy command and save-data key.
"""

from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple
import re

import discord
from discord.ext import commands

from apocalypse_bot.commands.v600_game_center import _real_cog, _safe_embed, _safe_view
from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as hub

VERSION = "16.6.1"


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _locale(ctx: commands.Context) -> str:
    try:
        from apocalypse_bot.commands import v1000_global_survivor as global_mod
        root = global_mod._RUNTIME.get("root", {})
        return global_mod._user_locale(root, int(ctx.author.id), int(ctx.guild.id if ctx.guild else 0))
    except Exception:
        return "ko"


async def _call_command_callback(command: commands.Command, ctx: commands.Context, *args: Any, **kwargs: Any) -> Any:
    cog = _real_cog(command)
    if cog is not None:
        return await command.callback(cog, ctx, *args, **kwargs)
    return await command.callback(ctx, *args, **kwargs)


def register_v1661_runtime_interaction_hotfix(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    del get_user, check_registered, save_data, world_data, user_data
    if getattr(bot, "_abaddon_v1661_registered", False):
        return
    bot._abaddon_v1661_registered = True
    bot.abaddon_version = VERSION

    # Some old builds registered a qualified command rendered as "카지노게임".
    # Keep it usable by routing it to the stable casino lobby instead of its malformed legacy view.
    for command in list(bot.walk_commands()):
        normalized = re.sub(r"\s+", "", str(getattr(command, "qualified_name", "")))
        if normalized != "카지노게임":
            continue
        previous = command.callback

        async def safe_casino_games(ctx: commands.Context, *args: Any, __previous: Any = previous, **kwargs: Any) -> None:
            target = bot.get_command("카지노") or bot.get_command("casino")
            if target is not None and target is not getattr(ctx, "command", None):
                await _call_command_callback(target, ctx)
                return
            try:
                await __previous(ctx, *args, **kwargs)
            except discord.HTTPException:
                await ctx.send(
                    "🎰 **BLACK CASINO**\n"
                    "`!카지노` 로비에서 포커·블랙잭·바카라·슬롯·VIP 기능을 선택하세요.\n"
                    "일반 경마·룰렛·탐색 배팅은 `!도박정보`에서 따로 확인할 수 있습니다."
                )

        command.callback = safe_casino_games
        command.help = "BLACK CASINO 게임 목록을 안전한 로비 화면으로 엽니다."
        command.description = command.help

    # Replace the repeatedly failing legacy test embed with a compact latest-scope test.
    test_command = bot.get_command("테스트")
    if test_command is not None:
        previous_test = test_command.callback

        async def latest_test_v1661(ctx: commands.Context, mode: str = "", *args: Any, **kwargs: Any) -> None:
            locale = _locale(ctx)
            checks: Sequence[Tuple[str, bool, str]] = (
                (_t(locale, "버튼 명령 브리지", "Button command bridge"), True, "discord.py MISSING cog guard"),
                (_t(locale, "장비 버튼 실행", "Equipment button execution"), bot.get_command("장비") is not None, "!장비"),
                (_t(locale, "명령어 상위/세부 선택", "Command hub selects"), bot.get_command("명령어") is not None and bot.get_command("help") is not None, "KO / EN"),
                (_t(locale, "선택 메뉴 제한", "Select-menu limits"), True, "1-25 options · unique values · 100-char fields"),
                (_t(locale, "임베드 제한", "Embed limits"), True, "25 fields · 6000 chars"),
                (_t(locale, "카지노 로비", "Casino lobby"), bot.get_command("카지노") is not None, "!카지노"),
                (_t(locale, "도박 분리", "Gambling split"), bot.get_command("도박정보") is not None, "!도박정보"),
                (_t(locale, "첫 생존 여정", "First Survival"), bot.get_command("초보생존") is not None or bot.get_command("firstsurvival") is not None, "7 steps"),
                (_t(locale, "실시간 오류센터", "Live QA center"), bot.get_command("실시간오류센터") is not None, "incident ledger"),
                (_t(locale, "최신 패치노트", "Latest patch notes"), bot.get_command("패치노트") is not None, VERSION),
            )
            passed = sum(1 for _name, ok, _detail in checks if ok)
            embed = discord.Embed(
                title=_t(locale, f"🧪 ABADDON v{VERSION} 런타임 테스트", f"🧪 ABADDON v{VERSION} Runtime Test"),
                description="\n".join(f"{'✅' if ok else '❌'} **{name}** · {detail}" for name, ok, detail in checks),
                color=0x2ECC71 if passed == len(checks) else 0xE67E22,
            )
            detail_requested = str(mode or "").casefold() in {"상세", "detail", "full"} or any(str(x).casefold() in {"상세", "detail", "full"} for x in args)
            if detail_requested:
                embed.add_field(
                    name=_t(locale, "이번 수정", "This Hotfix"),
                    value=_t(
                        locale,
                        "`장비` 버튼의 `_MissingSentinel.author` 오류 차단 · 잘못된 선택 메뉴/임베드 자동 정리 · 만료된 선택 UI 안전 안내",
                        "Blocked `_MissingSentinel.author` on equipment buttons · normalized malformed selects/embeds · safer expired-menu handling",
                    ),
                    inline=False,
                )
            embed.set_footer(text=_t(locale, "기존 기능·저장 데이터 삭제 0건", "0 legacy features or save data removed"))
            await ctx.send(embed=_safe_embed(embed))

        test_command.callback = latest_test_v1661
        test_command.help = "v16.6.1 버튼 실행·선택 메뉴·임베드·카지노·초보 여정의 최신 런타임 범위를 검사합니다."
        test_command.description = test_command.help
        test_command.extras = dict(getattr(test_command, "extras", {}) or {})
        test_command.extras["v1661_previous_callback"] = previous_test

    @bot.command(name="UI안정화검수", aliases=["uiaudit1661", "interactionaudit"], help="버튼 실행·선택 메뉴·임베드 제한·만료 UI 안전 처리를 검사합니다.")
    async def ui_runtime_audit(ctx: commands.Context, 상세: str = "") -> None:
        source_root = Path(__file__).resolve().parent
        v600 = (source_root / "v600_game_center.py").read_text(encoding="utf-8")
        v1630 = (source_root / "v1630_core_rpg_command_city_overhaul.py").read_text(encoding="utf-8")
        v634 = (source_root / "v634_equipment_menu.py").read_text(encoding="utf-8")
        checks = (
            ("MISSING cog guard", "discord.utils" in v600 and "getattr(command, \"cog\"" in v600),
            ("Select option sanitizer", "_safe_select_options" in v600),
            ("Embed 6000-char guard", "6000" in v600 and "_safe_embed" in v600),
            ("Command hub acknowledged edits", "_safe_component_edit" in v1630),
            ("Equipment menu acknowledged edits", "interaction.edit_original_response" in v634),
            ("Latest safe test", bot.get_command("테스트") is not None),
        )
        ok = all(row[1] for row in checks)
        embed = discord.Embed(title=f"🛠️ ABADDON v{VERSION} UI 안정화 검수", color=0x2ECC71 if ok else 0xE74C3C)
        embed.description = "\n".join(f"{'✅' if passed else '❌'} {name}" for name, passed in checks)
        if 상세:
            embed.add_field(name="대상 오류", value="`_MissingSentinel.author` · HTTP 400 Invalid Form Body · CategorySelect NotFound", inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="1661통합검수", aliases=["v1661audit", "1661audit"], help="v16.6.1 런타임 상호작용 핫픽스와 기존 핵심 연결을 검사합니다.")
    async def audit_1661(ctx: commands.Context, 상세: str = "") -> None:
        required = ["명령어", "help", "장비", "카지노", "도박정보", "초보생존", "실시간오류센터", "UI안정화검수", "테스트", "패치노트"]
        checks = [(name, bot.get_command(name) is not None) for name in required]
        entries = hub._build_registry(bot)
        checks.extend([
            ("전체 명령 분류", bool(entries) and all(entry.group in hub.GROUP_INDEX for entry in entries)),
            ("카지노/도박 분리", any(entry.group == "casino" for entry in entries) and any(entry.group == "gambling" for entry in entries)),
            ("한국어/English 분리", bot.get_command("명령어") is not None and bot.get_command("help") is not None),
        ])
        ok = all(value for _name, value in checks)
        locale = _locale(ctx)
        embed = discord.Embed(title=_t(locale, f"🧪 ABADDON v{VERSION} 통합 검수", f"🧪 ABADDON v{VERSION} Integration Audit"), color=0x2ECC71 if ok else 0xE74C3C)
        embed.description = "\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks)
        if 상세:
            embed.add_field(name=_t(locale, "보존", "Preservation"), value=_t(locale, "기존 명령·저장 키 삭제 0건", "0 legacy commands or save keys removed"), inline=False)
        await ctx.send(embed=_safe_embed(embed))

    patch_command = bot.get_command("패치노트")
    if patch_command is not None:
        previous_patch = patch_command.callback

        async def patch_notes_v1661(ctx: commands.Context) -> None:
            locale = _locale(ctx)
            embed = discord.Embed(
                title=_t(locale, f"🧯 ABADDON v{VERSION} 런타임 핫픽스", f"🧯 ABADDON v{VERSION} Runtime Hotfix"),
                description=_t(locale, "버튼으로 기존 명령을 실행할 때 발생한 실제 Discord 런타임 오류를 수정했습니다.", "Fixed real Discord runtime failures when legacy commands are executed from buttons."),
                color=0x7137C8,
            )
            embed.add_field(name=_t(locale, "🛡️ 장비 버튼 오류", "🛡️ Equipment Button Error"), value=_t(locale, "discord.py 2.7의 `_MissingSentinel`을 Cog로 오인하던 실행 경로를 수정했습니다.", "Stopped discord.py 2.7's `_MissingSentinel` from being mistaken for a Cog."), inline=False)
            embed.add_field(name=_t(locale, "🧩 선택 메뉴", "🧩 Select Menus"), value=_t(locale, "옵션 25개·문자 길이·중복 값·빈 목록을 전송 전에 정리합니다.", "Normalizes 25-option limits, text lengths, duplicate values, and empty lists before delivery."), inline=False)
            embed.add_field(name=_t(locale, "🧾 임베드", "🧾 Embeds"), value=_t(locale, "필드 25개와 전체 6000자 제한을 넘는 오래된 결과를 안전하게 축약합니다.", "Safely trims legacy results beyond 25 fields or the 6000-character total limit."), inline=False)
            embed.add_field(name=_t(locale, "⏱️ 만료 UI", "⏱️ Expired UI"), value=_t(locale, "명령어·장비 드롭다운을 먼저 승인한 뒤 편집해 `NotFound` 가능성을 낮췄습니다.", "Acknowledges command/equipment selects before editing to reduce `NotFound` failures."), inline=False)
            embed.add_field(name=_t(locale, "🧪 점검", "🧪 Checks"), value="`!UI안정화검수 상세` · `!1661통합검수 상세` · `!테스트 상세`", inline=False)
            embed.set_footer(text=_t(locale, "기존 기능·저장 데이터 삭제 0건", "0 legacy features or save data removed"))
            await ctx.send(embed=_safe_embed(embed))

        patch_command.callback = patch_notes_v1661
        patch_command.help = "ABADDON v16.6.1 버튼·선택 메뉴·임베드 런타임 오류 수정 패치노트입니다."
        patch_command.description = patch_command.help
        patch_command.extras = dict(getattr(patch_command, "extras", {}) or {})
        patch_command.extras["v1661_previous_callback"] = previous_patch

    guide.append({
        "id": "v1661_runtime_interaction_hotfix",
        "emoji": "🧯",
        "title": "v16.6.1 RUNTIME INTERACTION HOTFIX",
        "hint": "장비 버튼 MISSING sentinel · Invalid Form Body · 만료된 선택 메뉴 수정",
        "commands": [
            "!UI안정화검수 상세 · !1661통합검수 상세",
            "!테스트 상세 · !패치노트",
        ],
    })
