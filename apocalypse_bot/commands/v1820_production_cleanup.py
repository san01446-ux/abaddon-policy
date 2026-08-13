from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

import discord
from discord.ext import commands

from apocalypse_bot.commands.v1811_presence_owner_servers import _private_owner

VERSION = "18.2.0"
PATCH_DATE = "2026-08-13"

# Developer/regression commands stay available to the bot owner, but are removed
# from public command discovery. Operational server-admin diagnostics are not in
# this set and remain usable by server administrators.
DEV_EXACT = {
    "명령등록검수", "다국어검수", "명령어검수", "명령어UI검수", "초기기능검수",
    "UI검수", "UI안정화검수", "이미지검수", "1094이미지검수", "인연기록구버전",
    "중복검수", "안정화검수", "폐기후보", "연출검수", "게임진행검수",
    "실전게임검수", "카드게임검수", "동료검수", "홈페이지검수", "AI참가검수",
    "명령건강검진", "런타임청소검수", "죽은기능검수", "화면광택검수",
    "명령어전수검수", "도박분류검수", "도시부품검수", "경제검수", "오류검수",
    "경마배당검수", "경마표시검수", "화투패검수", "퀴즈검수", "DB검수",
    "경제정산검수", "재난알림검수", "알림UI검수", "테스트", "실시간피드테스트",
    "월드보스테스트", "월드보스테스트상태", "월드보스테스트공격", "월드보스테스트종료",
}
_VERSION_AUDIT_RE = re.compile(r"^\d{3,4}.*검수$")


def _source(command: commands.Command) -> str:
    return str(getattr(getattr(command, "callback", None), "__module__", "") or "")


def _is_dev_command(command: commands.Command) -> bool:
    name = str(getattr(command, "name", "") or "")
    if name in DEV_EXACT or _VERSION_AUDIT_RE.match(name):
        return True
    # Explicit legacy/developer aliases retained only for owner compatibility.
    aliases = {str(alias).casefold() for alias in (getattr(command, "aliases", []) or [])}
    if aliases & {"runtimecleansweep", "fullcommandaudit", "legacyimageaudit1094", "legacyrelationships", "legacybonds"}:
        return True
    return False


def register_v1820_production_cleanup(bot: commands.Bot) -> None:
    if getattr(bot, "_abaddon_v1820_registered", False):
        return

    async def owner_check(ctx: commands.Context) -> bool:
        return bool(await _private_owner(bot, ctx.author))

    hidden: List[str] = []
    retained_operational: List[str] = []
    for command in list(bot.walk_commands()):
        if _is_dev_command(command):
            command.hidden = True
            extras = dict(getattr(command, "extras", {}) or {})
            if not extras.get("v1820_owner_locked"):
                try:
                    command.add_check(owner_check)
                except AttributeError:
                    command.checks.append(owner_check)
                extras["v1820_owner_locked"] = True
                command.extras = extras
            hidden.append(str(command.qualified_name))
        else:
            name = str(getattr(command, "name", "") or "")
            if any(token in name for token in ("검수", "진단", "테스트", "점검")):
                retained_operational.append(str(command.qualified_name))

    # Remove hidden/owner-only commands from the public command center entirely,
    # rather than merely labeling them as restricted.
    catalog_count = 0
    try:
        from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as hub
        filtered = []
        # Mutate the existing list in place: v16.3/v18 command-center callbacks
        # close over this exact list object, so replacing the attribute alone
        # would leave the public UI showing stale developer commands.
        existing_entries = getattr(bot, "v1630_command_entries", None)
        source_entries = list(existing_entries) if isinstance(existing_entries, list) else hub._build_registry(bot)
        for entry in source_entries:
            command = bot.get_command(entry.qualified_name)
            if command is None or bool(getattr(command, "hidden", False)):
                continue
            if entry.source in {"v1811_presence_owner_servers", "v1815_owner_usage_audit", "v1820_production_cleanup"}:
                continue
            filtered.append(entry)
        filtered = [
            hub.CommandEntry(i, e.qualified_name, e.name, e.help_text, e.signature, e.aliases, e.source, e.section, e.group, e.restricted, e.is_group)
            for i, e in enumerate(filtered)
        ]
        if isinstance(existing_entries, list):
            existing_entries[:] = filtered
            entries = existing_entries
        else:
            entries = filtered
            setattr(bot, "v1630_command_entries", entries)
        setattr(bot, "v1630_command_index", {entry.qualified_name: entry for entry in entries})
        catalog_count = len(entries)
    except Exception as exc:
        print(f"[ABADDON v{VERSION} public catalog cleanup warning] {type(exc).__name__}: {exc}", flush=True)

    def command_source(name: str) -> str:
        command = bot.get_command(name)
        return _source(command).rsplit(".", 1)[-1] if command is not None else "missing"

    asset_root = Path(__file__).resolve().parents[1] / "assets"
    report: Dict[str, Any] = {
        "version": VERSION,
        "hidden_developer_commands": sorted(set(hidden)),
        "hidden_count": len(set(hidden)),
        "retained_operational_diagnostics": sorted(set(retained_operational)),
        "retained_count": len(set(retained_operational)),
        "public_catalog_count": catalog_count,
        "latest_relationship_source": command_source("인연"),
        "latest_image_audit_source": command_source("이미지검수"),
        "usage_storage": str(getattr(bot, "v1815_usage_storage", "unknown")),
    }
    setattr(bot, "v1820_cleanup_report", report)
    bot.abaddon_version = VERSION

    @bot.command(name="봇검수", aliases=["프로덕션검수", "정리현황", "productionaudit1820"], hidden=True, help="[봇 소유자 전용] v18.2.0 프로덕션 정리 상태를 통합 검사합니다.")
    async def production_audit(ctx: commands.Context, mode: str = "") -> None:
        if not await _private_owner(bot, ctx.author):
            return
        relationship_source = command_source("인연")
        image_source = command_source("이미지검수")
        registry = {}
        try:
            snapshot = getattr(bot, "v1330_registry_snapshot", None)
            registry = snapshot() if callable(snapshot) else {}
        except Exception:
            registry = {}
        duplicates = registry.get("duplicates", {}) if isinstance(registry, dict) else {}
        checks = [
            ("최신 !인연 → v17.2", relationship_source == "v1720_living_world_bonds"),
            ("최신 !이미지검수 → v16.2.1", image_source == "v1621_visual_command_hotfix"),
            ("서버 사용로그 SQLite 분리", str(getattr(bot, "v1815_usage_storage", "")) == "sqlite"),
            ("개발 검수 명령 공개 목록 제외", bool(hidden)),
            ("현재 런타임 접근 이름 중복 없음", not bool(duplicates)),
            ("v16.2.0 구버전 명령센터 중복 이미지 제거", not (asset_root / "v1620" / "previews" / "command_center_ko.png").exists()),
            ("v16.3.0 구버전 명령센터 중복 이미지 제거", not (asset_root / "v1630" / "previews" / "command_center_ko.png").exists()),
        ]
        passed = sum(1 for _label, ok in checks if ok)
        embed = discord.Embed(
            title=f"🧹 ABADDON v{VERSION} PRODUCTION CLEANUP · {passed}/{len(checks)}",
            color=0x2ECC71 if passed == len(checks) else 0xF1C40F,
        )
        embed.description = "\n".join(f"{'✅' if ok else '❌'} {label}" for label, ok in checks)
        embed.add_field(name="공개 정리", value=f"개발/회귀 명령 **{len(set(hidden))}개** 숨김+소유자 제한\n운영용 진단 **{len(set(retained_operational))}개** 유지\n공개 명령센터 **{catalog_count:,}개**", inline=False)
        embed.add_field(name="사용 로그", value=f"저장소 `{getattr(bot, 'v1815_usage_storage', 'unknown')}` · 메시지 내용/명령 인수 미수집", inline=False)
        if str(mode).casefold() in {"상세", "detail", "full", "전체"}:
            preview = ", ".join(sorted(set(hidden))[:30]) or "없음"
            embed.add_field(name="숨긴 개발 명령 일부", value=preview[:1024], inline=False)
            runtime_conflicts = registry.get("runtime_conflicts", []) if isinstance(registry, dict) else []
            embed.add_field(name="등록 보호기 기록", value=f"부팅 중 처리 {len(runtime_conflicts)}건 · 현재 중복 {len(duplicates)}건", inline=False)
        embed.set_footer(text="설치 서버 사용량: !서버사용통계 · 최근 로그: !서버사용로그")
        await ctx.send(embed=embed)

    # The command was added after the sweep; keep it private as well.
    audit_command = bot.get_command("봇검수")
    if audit_command is not None:
        audit_command.hidden = True

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def latest_patch(ctx: commands.Context) -> None:
            embed = discord.Embed(title="📜 ABADDON v18.2.0 PRODUCTION CLEANUP", color=0x7C4DFF)
            embed.add_field(name="🧩 레거시 충돌 정리", value="구버전 `!인연`/`!이미지검수` 이름 충돌을 분리해 최신 v17.2 인연과 v16.2.1 이미지 검수가 정상 등록됩니다.", inline=False)
            embed.add_field(name="🔒 개발 명령 정리", value=f"회귀·버전 검수 명령 **{len(set(hidden))}개**를 공개 명령센터에서 숨기고 봇 소유자 전용으로 제한했습니다.", inline=False)
            embed.add_field(name="🗄️ 사용 로그 DB 분리", value="서버별 직접명령/버튼 사용 기록을 SQLite 전용 테이블로 이동해 일반 사용 때문에 전체 JSON을 반복 저장하지 않습니다.", inline=False)
            embed.add_field(name="🧹 배포 정리", value="죽은 v10.7 규칙 모듈, 참조되지 않는 중복 미리보기, 과거 개발 검수 문서를 운영 배포본에서 제거했습니다.", inline=False)
            embed.set_footer(text=f"{PATCH_DATE} · 통합 검수: !봇검수 상세")
            await ctx.send(embed=embed)
        patch.callback = latest_patch
        patch.help = "ABADDON v18.2.0 프로덕션 정리 최신 패치노트입니다."
        patch.description = patch.help

    bot._abaddon_v1820_registered = True
    print(
        f"[ABADDON v{VERSION}] production cleanup registered: hidden_dev={len(set(hidden))} "
        f"retained_ops={len(set(retained_operational))} catalog={catalog_count}",
        flush=True,
    )
