from __future__ import annotations

"""ABADDON v10.9.3 command/UI stability hotfix.

This module is intentionally registered after every content patch so the audit
observes the final command registry and the latest callback replacements.
"""

from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands import v1000_global_survivor as localization_runtime
from apocalypse_bot.commands import v711_cute_interactions as command_catalog
from apocalypse_bot.commands import v1092_visual_status_horserace as visual_runtime
from apocalypse_bot.commands.v1010_companion_card_games import _ctx_locale, _t
from apocalypse_bot.commands.v1090_integrated_renewal import ALL_GAMES, GAME_EMOJI, _dashboard

VERSION = "10.9.3"
PATCH_DATE = "2026-08-04"

KNOWN_REPAIRED_EMOJIS: Mapping[str, str] = {
    "🀙": "🎴",
    "🂠": "🎴",
    "¼": "🔹",
    "½": "🔸",
    "✖️2": "✖️",
}


def _commands(bot: commands.Bot) -> List[commands.Command[Any, ..., Any]]:
    rows: List[commands.Command[Any, ..., Any]] = []
    seen = set()
    for command in bot.walk_commands():
        name = str(getattr(command, "qualified_name", "") or "").strip()
        if not name or name.casefold() in seen or getattr(command, "hidden", False):
            continue
        seen.add(name.casefold())
        rows.append(command)
    rows.sort(key=lambda item: item.qualified_name.casefold())
    return rows


def _registry_report(bot: commands.Bot) -> Dict[str, Any]:
    commands_list = _commands(bot)
    owners: Dict[str, str] = {}
    collisions: List[str] = []
    missing_description: List[str] = []
    missing_ascii: List[str] = []
    overlong_aliases: List[str] = []

    for command in commands_list:
        names = [command.name, *list(getattr(command, "aliases", []) or [])]
        for raw in names:
            key = str(raw).casefold().strip()
            if not key:
                continue
            previous = owners.get(key)
            if previous is not None and previous != command.qualified_name:
                collisions.append(f"{key}: {previous} / {command.qualified_name}")
            else:
                owners[key] = command.qualified_name
            if len(str(raw)) > 100:
                overlong_aliases.append(f"{command.qualified_name}:{raw}")

        description = str(getattr(command, "help", "") or getattr(command, "description", "") or "").strip()
        if not description:
            missing_description.append(command.qualified_name)
        if not any(str(name).isascii() for name in names):
            missing_ascii.append(command.qualified_name)

    return {
        "commands": commands_list,
        "count": len(commands_list),
        "access_names": len(owners),
        "collisions": sorted(set(collisions)),
        "missing_description": missing_description,
        "missing_ascii": missing_ascii,
        "overlong_aliases": overlong_aliases,
    }


def _emoji_report() -> Dict[str, Any]:
    sanitizer = getattr(localization_runtime, "_sanitize_ui_emoji", None)
    rows: Dict[str, str] = {}
    if callable(sanitizer):
        for bad, expected in KNOWN_REPAIRED_EMOJIS.items():
            rows[bad] = str(sanitizer(bad))
    return {
        "sanitizer": callable(sanitizer),
        "rows": rows,
        "all_repaired": bool(rows) and all(rows.get(bad) == expected for bad, expected in KNOWN_REPAIRED_EMOJIS.items()),
        "dori_emoji": GAME_EMOJI.get("도리짓고땡"),
    }


def _latest_checks(bot: commands.Bot) -> List[Tuple[str, bool, str]]:
    registry = _registry_report(bot)
    emoji = _emoji_report()
    avatar_route = bool(getattr(visual_runtime, "V1093_PROFILE_USES_DISCORD_AVATAR", False)) and callable(getattr(visual_runtime, "_avatar_bytes", None))
    return [
        ("전체 명령 레지스트리", registry["count"] > 900, f"commands={registry['count']} access_names={registry['access_names']}"),
        ("명령 이름·별칭 충돌", not registry["collisions"], f"collisions={len(registry['collisions'])}"),
        ("영문/ASCII 접근 경로", not registry["missing_ascii"], f"missing={len(registry['missing_ascii'])}"),
        ("명령 설명 표시 경로", callable(getattr(command_catalog, "_command_description", None)), f"explicit_missing={len(registry['missing_description'])} fallback=enabled"),
        ("컴포넌트 이모지 자동 정리", emoji["sanitizer"] and emoji["all_repaired"], str(emoji["rows"])),
        ("도리짓고땡 선택 이모지", emoji["dori_emoji"] == "🎴", str(emoji["dori_emoji"])),
        ("TextInput 폐기 경고 차단", bool(getattr(localization_runtime, "V1091_DEPRECATION_SAFE_LOCALIZER", False)), "TextInput.label skipped"),
        ("명령 도감 빠른 응답", bool(getattr(command_catalog, "V1093_COMMAND_CATALOG_FAST_ACK", False)), "defer + cached category index"),
        ("Discord 프로필 PNG 합성", avatar_route, "ctx.author.display_avatar.read()"),
        ("카드게임 선택 수 제한", len(ALL_GAMES) == 25, f"options={len(ALL_GAMES)}/25"),
        ("최신 패치 명령", bot.get_command("UI검수") is not None and bot.get_command("명령어검수") is not None, "!UI검수 / !명령어검수"),
        ("최신 패치노트", bot.get_command("패치노트") is not None, VERSION),
    ]


def _add_issue_field(embed: discord.Embed, locale: str, title_ko: str, title_en: str, values: Sequence[str]) -> None:
    if values:
        text = "\n".join(f"• `{value}`" for value in values[:12])
        if len(values) > 12:
            text += _t(locale, f"\n… 외 {len(values) - 12}개", f"\n… and {len(values) - 12} more")
    else:
        text = _t(locale, "없음", "None")
    embed.add_field(name=_t(locale, title_ko, title_en), value=text[:1024], inline=False)


def register_v1093_command_ui_audit(
    bot: commands.Bot,
    get_user: Callable[[int], MutableMapping[str, Any]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1093_registered", False):
        return
    bot._abaddon_v1093_registered = True

    # The v7 command catalogue may have been opened during an extension reload.
    # Rebuild its cache against the final v10.9.3 registry.
    invalidate = getattr(command_catalog, "invalidate_command_catalog_cache", None)
    if callable(invalidate):
        invalidate(bot)

    async def send_command_audit(ctx: commands.Context, 모드: str = "기본") -> None:
        locale = _ctx_locale(bot, ctx)
        report = _registry_report(bot)
        emoji = _emoji_report()
        failed = len(report["collisions"]) + len(report["missing_ascii"]) + len(report["overlong_aliases"])
        embed = _dashboard(
            bot,
            locale,
            f"🧪 ABADDON v{VERSION} 전체 명령·UI 검수",
            f"🧪 ABADDON v{VERSION} Full Command & UI Audit",
            "최종 등록된 명령·별칭·설명·선택 메뉴 이모지·명령 도감 응답 경로를 읽기 전용으로 검사합니다.",
            "Read-only audit of final commands, aliases, descriptions, component emoji and command-catalog response paths.",
            discord.Color.green() if failed == 0 else discord.Color.orange(),
        )
        embed.add_field(name=_t(locale, "명령어", "Commands"), value=f"**{report['count']:,}**", inline=True)
        embed.add_field(name=_t(locale, "실행 이름", "Access Names"), value=f"**{report['access_names']:,}**", inline=True)
        embed.add_field(name=_t(locale, "치명 문제", "Critical Issues"), value=f"**{failed:,}**", inline=True)
        embed.add_field(
            name=_t(locale, "UI 안전장치", "UI Guards"),
            value=_t(
                locale,
                f"이모지 정리 **{'정상' if emoji['all_repaired'] else '확인 필요'}** · 명령 도감 선응답/캐시 **적용** · 프로필 아바타 합성 **적용**",
                f"Emoji sanitation **{'OK' if emoji['all_repaired'] else 'CHECK'}** · early acknowledgement/cache **enabled** · profile avatar compositing **enabled**",
            ),
            inline=False,
        )
        detail = str(모드).casefold() in {"상세", "전체", "detail", "full"} or failed > 0
        if detail:
            _add_issue_field(embed, locale, "이름·별칭 충돌", "Name/Alias Collisions", report["collisions"])
            _add_issue_field(embed, locale, "영문 접근 누락", "Missing English Access", report["missing_ascii"])
            _add_issue_field(embed, locale, "설명 누락", "Missing Descriptions", report["missing_description"])
            _add_issue_field(embed, locale, "길이 초과", "Overlong Names", report["overlong_aliases"])
        embed.set_footer(text=_t(locale, "실제 Discord 버튼·모달 점검은 !테스트 상세 순서대로 확인", "Use !test detail for the live Discord button/modal checklist"))
        await ctx.send(embed=embed)

    existing_command_audit = bot.get_command("명령어검수")
    if existing_command_audit is not None:
        existing_command_audit.callback = send_command_audit
        existing_command_audit.help = "전체 명령·별칭·설명·UI 이모지·명령 도감 응답 경로를 검사합니다."
        existing_command_audit.description = existing_command_audit.help

    @bot.command(name="UI검수", aliases=["uiaudit", "componentaudit", "commanduiaudit"], help="Discord 버튼·선택 메뉴·모달과 명령 도감의 최신 안정화 상태를 검사합니다.")
    async def ui_audit(ctx: commands.Context, 모드: str = "기본") -> None:
        locale = _ctx_locale(bot, ctx)
        checks = _latest_checks(bot)
        passed = sum(1 for _name, ok, _detail in checks if ok)
        embed = _dashboard(
            bot,
            locale,
            f"🧩 ABADDON v{VERSION} UI 검수 · {passed}/{len(checks)}",
            f"🧩 ABADDON v{VERSION} UI Audit · {passed}/{len(checks)}",
            "Invalid Form Body·폐기 경고·상호작용 만료 재발 여부를 확인합니다.",
            "Checks for Invalid Form Body, deprecation warnings and interaction-expiry regressions.",
            discord.Color.green() if passed == len(checks) else discord.Color.orange(),
        )
        detail = str(모드).casefold() in {"상세", "전체", "detail", "full"} or passed != len(checks)
        if detail:
            for name, ok, value in checks:
                embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(value)[:1024], inline=True)
        else:
            embed.add_field(name=_t(locale, "결과", "Result"), value=f"✅ **{passed}** · ❌ **{len(checks)-passed}**\n`!UI검수 상세`", inline=False)
        await ctx.send(embed=embed)

    test_command = bot.get_command("테스트")
    if test_command is not None:
        async def v1093_test(ctx: commands.Context, 모드: str = "기본") -> None:
            locale = _ctx_locale(bot, ctx)
            checks = _latest_checks(bot)
            passed = sum(1 for _name, ok, _detail in checks if ok)
            failed = len(checks) - passed
            embed = _dashboard(
                bot,
                locale,
                f"🧪 ABADDON v{VERSION} 최신 패치 테스트 · {passed}/{len(checks)}",
                f"🧪 ABADDON v{VERSION} Latest Patch Test · {passed}/{len(checks)}",
                "이번 패치에서 수정한 전체 명령 UI·이모지·명령 도감·프로필 PNG 경로만 검사합니다.",
                "Checks only command UI, emoji, command catalogue and profile-PNG paths changed in this patch.",
                discord.Color.green() if failed == 0 else discord.Color.orange(),
            )
            detail = str(모드).casefold() in {"상세", "전체", "detail", "full"} or failed > 0
            if detail:
                for name, ok, value in checks:
                    embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=str(value)[:1024], inline=True)
            else:
                embed.add_field(name=_t(locale, "결과", "Result"), value=f"✅ **{passed}** · ❌ **{failed}**\n`!테스트 상세`", inline=False)
            embed.add_field(
                name=_t(locale, "실제 배포 판별", "Live Deployment Check"),
                value=_t(locale, "부팅 로그에 `[ABADDON v10.9.3] command_ui_audit=enabled`가 없으면 이전 빌드입니다.", "If boot logs lack `[ABADDON v10.9.3] command_ui_audit=enabled`, an older build is running."),
                inline=False,
            )
            await ctx.send(embed=embed)
        test_command.callback = v1093_test
        test_command.help = "v10.9.3에서 수정한 전체 명령 UI·이모지·명령 도감·프로필 PNG 경로만 검사합니다. `!테스트 상세` 지원."
        test_command.description = test_command.help

    patch_notes = bot.get_command("패치노트")
    if patch_notes is not None:
        async def v1093_patch_notes(ctx: commands.Context) -> None:
            locale = _ctx_locale(bot, ctx)
            embed = _dashboard(
                bot,
                locale,
                f"🧩 ABADDON v{VERSION} — 전체 명령 UI 안정화",
                f"🧩 ABADDON v{VERSION} — Full Command UI Stability",
                "이번 핫픽스에서 실제 수정한 항목만 표시합니다.",
                "Only changes actually made in this hotfix are shown.",
                discord.Color.dark_teal(),
            )
            embed.add_field(name=_t(locale, "🚫 Invalid emoji 수정", "🚫 Invalid Emoji Fix"), value=_t(locale, "카드게임·섯다·조커잡기 UI의 Discord 비지원 문자 5종을 안전한 이모지로 교체하고 전송 직전 자동 정리 추가", "Replaced five unsupported component glyphs and added pre-send sanitation"), inline=False)
            embed.add_field(name=_t(locale, "⏱️ 명령 도감 응답", "⏱️ Command Catalogue Response"), value=_t(locale, "약 1,000개 명령 분류를 매 클릭마다 다시 계산하던 구조를 캐시하고, 카테고리·페이지 클릭을 먼저 승인해 Unknown interaction 완화", "Caches the roughly 1,000-command category index and acknowledges clicks before rebuilding views"), inline=False)
            embed.add_field(name=_t(locale, "🧹 폐기 경고 제거", "🧹 Deprecation Cleanup"), value=_t(locale, "TextInput.label 직접 수정 경로를 최신 Label 컨테이너로 교체하고 공용 번역기는 TextInput을 건드리지 않음", "Replaced direct TextInput.label mutation with modern Label containers; the localizer skips TextInput labels"), inline=False)
            embed.add_field(name=_t(locale, "🖼️ Discord 프로필 합성", "🖼️ Discord Avatar Compositing"), value=_t(locale, "`!정보` PNG는 실행자의 `display_avatar`를 읽어 카드 왼쪽 상단에 합성하며, 다운로드 실패 시 이름 이니셜로 대체", "`!info` reads the caller's display_avatar into the PNG; initials are used only if download fails"), inline=False)
            embed.add_field(name=_t(locale, "🧪 전체 명령 검수", "🧪 Full Command Audit"), value=_t(locale, "`!명령어검수 상세` · `!UI검수 상세` · `!테스트 상세`를 v10.9.3 범위로 최신화", "Updated full command, UI and latest-patch audits for v10.9.3"), inline=False)
            await ctx.send(embed=embed)
        patch_notes.callback = v1093_patch_notes
        patch_notes.help = f"ABADDON v{VERSION} 최신 패치노트를 표시합니다."
        patch_notes.description = patch_notes.help

    guide[:] = [row for row in guide if row.get("id") != "v1093_command_ui_audit"]
    guide.append({
        "id": "v1093_command_ui_audit",
        "emoji": "🧪",
        "title": "v10.9.3 전체 명령 UI 안정화",
        "hint": "Invalid emoji · 명령 도감 선응답/캐시 · TextInput 경고 · Discord 프로필 PNG · 최신 범위 검수",
        "commands": [
            "!명령어검수 상세 · !commandaudit detail",
            "!UI검수 상세 · !uiaudit detail",
            "!테스트 상세 · !test detail",
            "!정보 · !info",
            "!패치노트 · !patchnotes",
        ],
    })

    bot.v1093_version = VERSION  # type: ignore[attr-defined]
    bot.v1093_latest_checks = lambda: _latest_checks(bot)  # type: ignore[attr-defined]
    bot.v1093_command_registry_report = lambda: _registry_report(bot)  # type: ignore[attr-defined]
    print(f"[ABADDON v{VERSION}] command_ui_audit=enabled emoji_sanitizer=enabled catalog_fast_ack=enabled profile_avatar=discord", flush=True)
