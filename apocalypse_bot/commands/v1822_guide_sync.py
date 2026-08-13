from __future__ import annotations

"""ABADDON v18.2.2 guide synchronization and guide-regression audit.

Keeps public help surfaces aligned with the actually registered command tree.
This module does not mutate survivor/game data.
"""

import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v1811_presence_owner_servers import _private_owner

VERSION = "18.2.2"

GUIDE_COMMANDS: Tuple[str, ...] = (
    "명령어", "도움말", "처음", "시작안내", "복귀안내", "봇소개",
    "도박정보", "카지노도움말", "카드게임", "파밍", "다크존",
    "운영도움말", "운영도구도움말", "운영편의도움말",
    "관리확장도움말", "보안센터도움말", "접수센터도움말",
    "채널규칙", "서버메뉴",
)

GAMBLING_CURRENT: Tuple[str, ...] = (
    "도박정보", "도박잔액", "탐색", "주파수", "룰렛", "파산신청",
    "경마", "경마장", "경마전적", "괴질탈출", "비상주파수", "지뢰찾기",
    "돌연변이경주", "돌연변이배팅", "선물거래", "괴수투기장",
    "생존룰렛", "생존선택", "정부지원금",
)

CASINO_CURRENT: Tuple[str, ...] = (
    "카지노", "카지노칩", "카지노환전", "카지노VIP", "카지노잭팟",
    "카지노미션", "카지노미션보상", "카지노업적", "카지노상점", "카지노구매",
    "카지노기록", "카지노랭킹", "카지노딜러", "카지노시즌랭킹",
    "블랙잭", "하이로우", "슬롯", "다이스", "바카라", "럭키휠", "코인플립", "올인",
)


def _exists(bot: commands.Bot, name: str) -> bool:
    return bot.get_command(str(name)) is not None


def _guide_roots(guide: Sequence[Mapping[str, Any]]) -> List[str]:
    roots: List[str] = []
    for category in guide:
        for row in category.get("commands", []) if isinstance(category, Mapping) else []:
            for token in re.findall(r"!([가-힣A-Za-z0-9_]+)", str(row)):
                if token not in roots:
                    roots.append(token)
    return roots


def register_v1822_guide_sync(
    bot: commands.Bot,
    guide: Sequence[Mapping[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1822_registered", False):
        return

    # Contextual UI should surface only non-destructive status/help actions from the
    # enlarged general-gambling family. Starting a wager is never auto-suggested.
    try:
        from apocalypse_bot.commands import v1803_contextual_ui as contextual
        contextual.SAFE_RELATED_BY_GROUP["gambling"] = (
            "도박정보", "도박잔액", "경마장", "정부지원금", "카지노", "카드게임",
        )
        contextual.SAFE_RELATED_BY_COMMAND["도박정보"] = (
            "도박잔액", "경마장", "카지노", "카드게임",
        )
    except Exception as exc:
        print(f"[ABADDON v{VERSION} contextual guide warning] {type(exc).__name__}: {exc}", flush=True)

    @bot.command(
        name="안내검수",
        aliases=["가이드검수", "helpaudit", "guideaudit"],
        hidden=True,
        help="[봇 소유자 전용] 안내/도움말이 현재 등록 명령과 일치하는지 검사합니다.",
    )
    async def guide_audit(ctx: commands.Context) -> None:
        if not await _private_owner(bot, ctx.author):
            return

        missing_guides = [name for name in GUIDE_COMMANDS if not _exists(bot, name)]
        missing_gambling = [name for name in GAMBLING_CURRENT if not _exists(bot, name)]
        missing_casino = [name for name in CASINO_CURRENT if not _exists(bot, name)]
        guide_roots = _guide_roots(guide)
        unresolved_roots = [name for name in guide_roots if not _exists(bot, name)]
        alias_ok = bot.all_commands.get("도박안내") is bot.get_command("도박정보")

        # The grouped slash tree is created after this module registers, but the
        # command itself is executed after startup so the counters are available.
        slash_root = int(getattr(bot, "_abaddon_slash_root_count", len(bot.tree.get_commands())))
        slash_total = int(getattr(bot, "_abaddon_slash_total_count", sum(1 for _ in bot.tree.walk_commands())))

        checks = [
            ("주요 안내 명령 등록", not missing_guides, ", ".join(missing_guides[:8]) or "정상"),
            ("일반 도박 최신 기능", not missing_gambling, ", ".join(missing_gambling[:8]) or "정상"),
            ("카지노 최신 기능", not missing_casino, ", ".join(missing_casino[:8]) or "정상"),
            ("!명령어 안내 참조", not unresolved_roots, ", ".join(unresolved_roots[:8]) or "정상"),
            ("!도박안내 별칭", alias_ok, "도박정보 연결" if alias_ok else "별칭 연결 실패"),
            ("슬래시 최상위 제한", slash_root <= 100, f"{slash_root}/100 · 전체 {slash_total}"),
        ]
        embed = discord.Embed(
            title=f"🧪 ABADDON v{VERSION} 안내 동기화 검수",
            description="실제 런타임 등록 명령을 기준으로 안내 링크와 도박/카지노 분리를 검사합니다.",
            color=discord.Color.green() if all(ok for _n, ok, _d in checks) else discord.Color.orange(),
        )
        for name, ok, detail in checks:
            embed.add_field(name=("✅ " if ok else "❌ ") + name, value=detail[:1024], inline=False)
        embed.set_footer(text="제작자 전용 · 게임/생존자 데이터 변경 없음")
        await ctx.send(embed=embed)

    @bot.command(
        name="1822검수",
        aliases=["v1822audit", "1822audit"],
        hidden=True,
        help="[봇 소유자 전용] v18.2.2 안내 최신화 핵심 항목을 빠르게 검사합니다.",
    )
    async def audit_1822(ctx: commands.Context) -> None:
        if not await _private_owner(bot, ctx.author):
            return
        checks = [
            ("도박정보", _exists(bot, "도박정보")),
            ("도박안내 별칭", bot.all_commands.get("도박안내") is bot.get_command("도박정보")),
            ("경마", _exists(bot, "경마")),
            ("지뢰찾기", _exists(bot, "지뢰찾기")),
            ("선물거래", _exists(bot, "선물거래")),
            ("생존룰렛", _exists(bot, "생존룰렛")),
            ("카지노도움말", _exists(bot, "카지노도움말")),
            ("시작안내", _exists(bot, "시작안내")),
            ("복귀안내", _exists(bot, "복귀안내")),
            ("안내검수", _exists(bot, "안내검수")),
        ]
        await ctx.send(
            f"🧪 **ABADDON v{VERSION} GUIDE SYNC**\n"
            + "\n".join(("✅" if ok else "❌") + f" {name}" for name, ok in checks)
        )

    patch_cmd = bot.get_command("패치노트")
    if patch_cmd is not None:
        async def patch_v1822(ctx: commands.Context) -> None:
            embed = discord.Embed(
                title="📜 ABADDON v18.2.2 · GUIDE SYNC",
                description="오래된 안내 문구와 실제 기능의 차이를 정리하고 일반 도박/카지노/초보 안내를 현재 명령 기준으로 동기화했습니다.",
                color=0x7C4DFF,
            )
            embed.add_field(name="🎲 도박 안내", value="알바 40회·8초, 코인 60초·30회로 실제 수치 수정 · 경마/지뢰/괴질/비상주파수/돌연변이/선물거래/괴수투기장/생존룰렛 추가", inline=False)
            embed.add_field(name="🎰 카지노", value="일반 도박과 분리 표시 · 기존 카지노 게임/확장/개인 카지노 계열 안내 유지·보강", inline=False)
            embed.add_field(name="🧭 시작/복귀", value="v10 시대의 시작/복귀 문구를 현재 `!처음`, `!초보센터`, `!생존허브`, FINAL ECLIPSE/박물관/연결 루프 기준으로 교체", inline=False)
            embed.add_field(name="⌨️ 슬래시", value="`/도박` 그룹에 현재 일반 도박의 안전한 최신 명령 경로를 추가", inline=False)
            embed.add_field(name="🧪 검수", value="`!안내검수` · `!1822검수`", inline=False)
            embed.set_footer(text="기존 유저 데이터 변경 0건 · /var/data 구조 유지")
            await ctx.send(embed=embed)
        patch_cmd.callback = patch_v1822
        patch_cmd.help = "ABADDON v18.2.2 안내/도움말 최신화 패치노트입니다."
        patch_cmd.description = patch_cmd.help

    # Refresh the final public command catalog after alias/guide synchronization.
    try:
        from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as hub
        entries = hub._build_registry(bot)
        setattr(bot, "v1630_command_entries", entries)
        setattr(bot, "v1630_command_index", {e.qualified_name: e for e in entries})
    except Exception as exc:
        print(f"[ABADDON v{VERSION} catalog refresh warning] {type(exc).__name__}: {exc}", flush=True)

    bot._abaddon_v1822_registered = True
    bot.abaddon_version = VERSION
    print(f"[ABADDON v{VERSION}] guide sync + guide regression audit registered", flush=True)
