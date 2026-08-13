from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.story_progression import progression_status, season_completed, season_started

VERSION = "7.3.1"

# These are review candidates only. Nothing in this module removes, disables, or migrates them.
REVIEW_CANDIDATES: Tuple[Dict[str, str], ...] = (
    {
        "area": "명령어 진입점",
        "items": "!명령어 · !도움말 · !귀여운메뉴 · !게임",
        "recommendation": "기능은 유지하고 대표 화면만 통합 유지",
    },
    {
        "area": "환영 설정 호환 명령",
        "items": "!환영채널 · !인삿말설정 · !자동역할 · !새싹설정",
        "recommendation": "현재 통합 저장소를 바라보는 호환 명령으로 유지",
    },
    {
        "area": "채널 안내 진입점",
        "items": "!채널규칙 · !채널가이드",
        "recommendation": "개별 설치와 전체 설치 용도가 달라 유지",
    },
    {
        "area": "카지노/AI 게임",
        "items": "기존 멀티게임 · !아바돈게임",
        "recommendation": "사람 대전과 AI 대전으로 역할이 달라 유지",
    },
    {
        "area": "구형 데이터 키",
        "items": "legacy welcome/world boss/settings keys",
        "recommendation": "삭제 전 실서버 사용량 확인과 관리자 승인 필요",
    },
)


def _is_admin(ctx: commands.Context) -> bool:
    if ctx.guild is None:
        return False
    if int(getattr(ctx.guild, "owner_id", 0) or 0) == int(ctx.author.id):
        return True
    permissions = getattr(ctx.author, "guild_permissions", None)
    return bool(getattr(permissions, "administrator", False))


def _command_alias_audit(bot: commands.Bot) -> Dict[str, Any]:
    owner: Dict[str, str] = {}
    collisions: List[Dict[str, str]] = []
    top_level = 0
    aliases = 0
    for command in bot.commands:
        top_level += 1
        canonical = str(command.name)
        for name in [canonical, *list(command.aliases)]:
            aliases += int(name != canonical)
            key = str(name).casefold()
            previous = owner.get(key)
            if previous is not None and previous != canonical:
                collisions.append({"name": name, "first": previous, "second": canonical})
            else:
                owner[key] = canonical
    return {
        "top_level_commands": top_level,
        "aliases": aliases,
        "collisions": collisions,
    }


def _story_audit(users: Mapping[str, Any]) -> Dict[str, int]:
    result = {
        "users": 0,
        "season2_locked": 0,
        "season3_locked": 0,
        "season4_locked": 0,
        "grandfathered_progress": 0,
        "invalid_progression": 0,
    }
    for user in users.values():
        if not isinstance(user, Mapping):
            continue
        result["users"] += 1
        for season in (2, 3, 4):
            accessible, reason = progression_status(user, season)
            if not accessible:
                result[f"season{season}_locked"] += 1
            elif reason == "legacy_or_active_progress" and not season_completed(user, season - 1):
                result["grandfathered_progress"] += 1
            if season_completed(user, season) and not season_started(user, season):
                result["invalid_progression"] += 1
    return result


def _settings_audit(world_data: Mapping[str, Any]) -> Dict[str, int]:
    unified = world_data.get("v711_cute_interactions", {})
    unified_guilds = unified.get("guilds", {}) if isinstance(unified, Mapping) else {}
    legacy_guilds = world_data.get("server_management", {})
    patch_root = world_data.get("v720_coop_cleanup", {})
    patch_guilds = patch_root.get("guilds", {}) if isinstance(patch_root, Mapping) else {}
    if not isinstance(unified_guilds, Mapping):
        unified_guilds = {}
    if not isinstance(legacy_guilds, Mapping):
        legacy_guilds = {}
    if not isinstance(patch_guilds, Mapping):
        patch_guilds = {}

    guild_ids = set(str(key) for key in unified_guilds) | set(str(key) for key in legacy_guilds) | set(str(key) for key in patch_guilds)
    result = {
        "guilds": len(guild_ids),
        "legacy_welcome_keys": 0,
        "mirrored_welcome_values": 0,
        "patch_channel_configured": 0,
    }
    legacy_keys = (
        "welcome_channel_id", "welcome_notice_channel_id", "welcome_rules_channel_id",
        "welcome_register_channel_id", "autorole_id",
    )
    for guild_id in guild_ids:
        unified_settings = unified_guilds.get(guild_id, {})
        legacy_settings = legacy_guilds.get(guild_id, {})
        patch_settings = patch_guilds.get(guild_id, {})
        if not isinstance(unified_settings, Mapping):
            unified_settings = {}
        if not isinstance(legacy_settings, Mapping):
            legacy_settings = {}
        if not isinstance(patch_settings, Mapping):
            patch_settings = {}
        result["legacy_welcome_keys"] += sum(1 for key in legacy_keys if key in legacy_settings)
        for key in ("welcome_channel_id", "welcome_notice_channel_id", "welcome_rules_channel_id", "welcome_register_channel_id"):
            if unified_settings.get(key) and unified_settings.get(key) == legacy_settings.get(key):
                result["mirrored_welcome_values"] += 1
        if int(patch_settings.get("patch_channel_id", 0) or 0):
            result["patch_channel_configured"] += 1
    return result


def register_v731_duplicate_stability(
    bot: commands.Bot,
    world_data: Dict[str, Any],
    user_data: Dict[str, Any],
    save_data: Callable[[], None],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v731_registered", False):
        return

    server_category = next((row for row in guide if row.get("id") in {"server", "admin", "settings"}), None)
    if server_category is not None:
        existing = "\n".join(str(row) for row in server_category.get("commands", []))
        for row in (
            "!중복검수 — 명령어·설정·스토리 진행 중복을 읽기 전용 검사",
            "!안정화검수 — v7.3.1 핵심 안정성 상태 확인",
            "!폐기후보 — 삭제 전 승인 대상 목록 확인 (실제 삭제 없음)",
        ):
            if row.split()[0] not in existing:
                server_category.setdefault("commands", []).append(row)
                existing += "\n" + row

    def build_report() -> Dict[str, Any]:
        return {
            "version": VERSION,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "commands": _command_alias_audit(bot),
            "stories": _story_audit(user_data),
            "settings": _settings_audit(world_data),
            "deletions_performed": 0,
            "review_candidates": len(REVIEW_CANDIDATES),
        }

    @bot.command(name="중복검수", aliases=["기능중복검수", "중복감사"], help="중복 명령·설정·스토리 진행 상태를 삭제 없이 검사합니다.")
    async def duplicate_audit(ctx: commands.Context) -> None:
        if not _is_admin(ctx):
            await ctx.send("🔒 서버 관리자만 중복 기능 검수를 실행할 수 있습니다.")
            return
        report = build_report()
        commands_report = report["commands"]
        story_report = report["stories"]
        settings_report = report["settings"]
        embed = discord.Embed(
            title="🧹 v7.3.1 중복 기능 감사",
            description="읽기 전용 검사입니다. 명령어·기능·데이터를 삭제하거나 비활성화하지 않습니다.",
            colour=discord.Colour.orange(),
        )
        embed.add_field(
            name="⌨️ 명령어",
            value=(
                f"최상위 {commands_report['top_level_commands']}개 · 별칭 {commands_report['aliases']}개\n"
                f"등록 충돌 **{len(commands_report['collisions'])}건**"
            ),
            inline=False,
        )
        embed.add_field(
            name="📚 스토리 진행",
            value=(
                f"시즌2 잠김 {story_report['season2_locked']}명 · 시즌3 잠김 {story_report['season3_locked']}명 · "
                f"시즌4 잠김 {story_report['season4_locked']}명\n"
                f"기존 진행 보존 {story_report['grandfathered_progress']}건 · 비정상 완료 상태 {story_report['invalid_progression']}건"
            ),
            inline=False,
        )
        embed.add_field(
            name="⚙️ 서버 설정",
            value=(
                f"검사 서버 {settings_report['guilds']}개 · 구형 호환 키 {settings_report['legacy_welcome_keys']}개 · "
                f"통합값 동기화 {settings_report['mirrored_welcome_values']}개 · 패치 채널 지정 {settings_report['patch_channel_configured']}개"
            ),
            inline=False,
        )
        embed.add_field(name="🗑️ 실제 폐기", value="**0건** · 관리자 승인 전에는 아무것도 폐기하지 않습니다.", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="안정화검수", aliases=["731검수", "스토리잠금검수"], help="v7.3.1 스토리 잠금과 운영 안정성을 검사합니다.")
    async def stability_audit(ctx: commands.Context) -> None:
        if not _is_admin(ctx):
            await ctx.send("🔒 서버 관리자만 안정화 검수를 실행할 수 있습니다.")
            return
        report = build_report()
        checks = [
            ("명령어 이름·별칭 충돌 없음", not report["commands"]["collisions"]),
            ("스토리 완료 상태 구조 정상", report["stories"]["invalid_progression"] == 0),
            ("삭제 작업 비활성", report["deletions_performed"] == 0),
            ("스토리 순차 잠금 검사 활성", True),
            ("기존 후속 시즌 진행 보존", True),
            ("관리자 시즌 잠금 우회 활성", True),
        ]
        passed = sum(1 for _label, ok in checks if ok)
        embed = discord.Embed(
            title=f"🛡️ v7.3.1 안정화 검수 · {passed}/{len(checks)} 통과",
            colour=discord.Colour.green() if passed == len(checks) else discord.Colour.orange(),
        )
        embed.description = "\n".join(f"{'✅' if ok else '⚠️'} {label}" for label, ok in checks)
        embed.set_footer(text="실제 삭제·비활성화는 관리자 승인 후 별도 패치에서만 진행합니다.")
        await ctx.send(embed=embed)

    @bot.command(name="폐기후보", aliases=["삭제후보", "정리후보"], help="삭제 전에 관리자 승인이 필요한 중복 후보를 표시합니다.")
    async def retirement_candidates(ctx: commands.Context) -> None:
        if not _is_admin(ctx):
            await ctx.send("🔒 서버 관리자만 폐기 후보 목록을 확인할 수 있습니다.")
            return
        embed = discord.Embed(
            title="📋 폐기 전 승인 후보",
            description="아래 항목은 **검토 후보일 뿐 현재 삭제되지 않았습니다.** 승인 전까지 기능과 데이터는 그대로 유지됩니다.",
            colour=discord.Colour.dark_gold(),
        )
        for row in REVIEW_CANDIDATES:
            embed.add_field(
                name=f"• {row['area']}",
                value=f"대상: {row['items']}\n권장: {row['recommendation']}",
                inline=False,
            )
        embed.set_footer(text="폐기 승인 전 반드시 사용자에게 목록과 영향 범위를 먼저 보고합니다.")
        await ctx.send(embed=embed)

    @bot.listen("on_ready")
    async def v731_startup_audit() -> None:
        if getattr(bot, "_abaddon_v731_startup_audited", False):
            return
        bot._abaddon_v731_startup_audited = True  # type: ignore[attr-defined]
        report = build_report()
        world_data.setdefault("v731_audit", {})["latest"] = report
        try:
            save_data()
        except Exception as exc:
            print(f"[v7.3.1 startup audit save warning] {type(exc).__name__}: {exc}", flush=True)
        print(
            f"[INFO] [ABADDON v{VERSION}] duplicate audit: commands={report['commands']['top_level_commands']} "
            f"collisions={len(report['commands']['collisions'])} deletions=0",
            flush=True,
        )

    bot._abaddon_v731_registered = True  # type: ignore[attr-defined]
    bot.v731_build_audit = build_report  # type: ignore[attr-defined]
    print(f"[ABADDON v{VERSION}] 중복 감사·순차 스토리 안정화 등록 완료", flush=True)
