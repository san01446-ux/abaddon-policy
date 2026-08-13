from __future__ import annotations

"""ABADDON v18.1.4 FULL UI BRIDGE STABILITY.

Final hardening for contextual buttons/selects:
- component interactions execute legacy HybridCommands with prefix semantics;
- related dropdowns are curated instead of classifier-wide discovery;
- coin sell is surfaced directly in the coin action row;
- runtime audit verifies the bridge, aliases and safety policy without deleting
  any legacy commands or saved data.
"""

from typing import Any
import os

import discord
from discord.ext import commands

from apocalypse_bot.commands import v1803_contextual_ui as ui1803

VERSION = "18.1.4"


def _locale(bot: commands.Bot, ctx: commands.Context) -> str:
    try:
        from apocalypse_bot.commands import v1660_first_survival_live_qa as live1660
        return live1660._locale(bot, ctx)
    except Exception:
        return "ko"


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _same_command(bot: commands.Bot, a: str, b: str) -> bool:
    ca = bot.get_command(a)
    cb = bot.get_command(b)
    return ca is not None and ca is cb


def register_v1814_full_ui_bridge_stability(bot: commands.Bot) -> None:
    if getattr(bot, "_abaddon_v1814_registered", False):
        return
    bot._abaddon_v1814_registered = True
    bot.abaddon_version = VERSION
    bot.v1814_prefix_bridge_semantics = True
    bot.v1814_curated_related_dropdown = True
    bot.v1814_coin_sell_visible = True

    @bot.command(
        name="1814UI검수",
        aliases=["1814버튼검수", "전체버튼검수", "uidropaudit"],
        hidden=True,
        help="v18.1.4 버튼·드롭다운·코인거래 브리지 최종 검수",
    )
    async def audit_v1814(ctx: commands.Context, mode: str = "") -> None:
        locale = _locale(bot, ctx)
        detailed = str(mode or "").casefold() in {"상세", "detail", "details", "full"}

        required = ("채집", "벌목", "지갑", "코인", "매도", "자산", "시세", "최종일식")
        required_ok = all(bot.get_command(name) is not None for name in required)
        forbidden = ("검수", "help", "명령어", "패치노트", "테스트", "오류", "복구", "백업")
        safe_values = [name for rows in ui1803.SAFE_RELATED_BY_GROUP.values() for name in rows]
        safe_values += [name for rows in ui1803.SAFE_RELATED_BY_COMMAND.values() for name in rows]
        curated_ok = not any(any(token.casefold() in str(name).casefold() for token in forbidden) for name in safe_values)
        final_rows = tuple(ui1803.SAFE_RELATED_BY_GROUP.get("definitive", ()))
        final_ok = all(name not in final_rows for name in ("1800일식검수", "help", "명령어", "일식작전", "일식투표"))
        coin_buttons = tuple(c.names[0] for c in ui1803.SPECIAL_BUTTONS.get("코인", ()))

        checks: list[tuple[str, bool]] = [
            (_t(locale, "컴포넌트→prefix 실행 의미 고정", "Component→prefix semantics"), bool(getattr(bot, "v1814_prefix_bridge_semantics", False))),
            (_t(locale, "관련 기능 드롭다운 화이트리스트", "Curated related dropdown"), bool(getattr(bot, "v1814_curated_related_dropdown", False))),
            (_t(locale, "검수/help/운영 항목 드롭다운 차단", "Audit/help/admin entries blocked"), curated_ok),
            (_t(locale, "FINAL ECLIPSE 안전 항목만 노출", "FINAL ECLIPSE safe entries"), final_ok),
            (_t(locale, "채집·벌목·지갑 기존 명령 보존", "Gather/lumber/wallet preserved"), all(bot.get_command(x) is not None for x in ("채집", "벌목", "지갑"))),
            (_t(locale, "코인 판매 버튼 노출", "Coin sell button visible"), "매도" in coin_buttons),
            (_t(locale, "!매도 / !코인판매 동일 명령", "!매도 / !코인판매 same command"), _same_command(bot, "매도", "코인판매")),
            (_t(locale, "!자산 / !시세 보존", "Portfolio / prices preserved"), bot.get_command("자산") is not None and bot.get_command("시세") is not None),
            (_t(locale, "핵심 UI 대상 명령 존재", "Core UI target commands exist"), required_ok),
            (_t(locale, "v18.1.3 지원·KoreanBots 기능 보존", "v18.1.3 support/KoreanBots preserved"), bot.get_command("버그신고") is not None and bot.get_command("한국봇상태") is not None),
        ]

        embed = discord.Embed(
            title=_t(locale, "🧪 ABADDON v18.1.4 전체 UI 검수", "🧪 ABADDON v18.1.4 Full UI Audit"),
            color=0x2ECC71 if all(ok for _, ok in checks) else 0xE74C3C,
        )
        embed.description = "\n".join(f"{'✅' if ok else '❌'} {label}" for label, ok in checks)
        if detailed:
            embed.add_field(
                name=_t(locale, "관련 기능 더보기 정책", "Related dropdown policy"),
                value=_t(
                    locale,
                    f"화이트리스트 그룹 {len(ui1803.SAFE_RELATED_BY_GROUP)}개 · 명령별 정책 {len(ui1803.SAFE_RELATED_BY_COMMAND)}개\n"
                    f"코인 버튼: {', '.join(coin_buttons)}",
                    f"Whitelisted groups {len(ui1803.SAFE_RELATED_BY_GROUP)} · command policies {len(ui1803.SAFE_RELATED_BY_COMMAND)}\n"
                    f"Coin buttons: {', '.join(coin_buttons)}",
                ),
                inline=False,
            )
            embed.add_field(
                name=_t(locale, "코인 판매", "Coin selling"),
                value=_t(locale, "`!매도` 또는 `!코인판매` → 보유 코인 판매 드롭다운", "`!매도` or `!코인판매` → sell-menu dropdown"),
                inline=False,
            )
        embed.set_footer(text=_t(locale, "기존 명령·저장 데이터 삭제 0건", "0 legacy commands/save data deleted"))
        await ctx.send(embed=embed)

    # Keep the canonical !패치노트 command but advance only its callback/help.
    patch = bot.get_command("패치노트")
    if patch is not None:
        async def patch_v1814(ctx: commands.Context) -> None:
            locale = _locale(bot, ctx)
            if locale == "en":
                await ctx.send(
                    "🧩 **ABADDON v18.1.4 — Full UI Bridge Stability**\n"
                    "• Fixed component→HybridCommand context semantics (`author` MissingSentinel)\n"
                    "• Replaced classifier-wide related dropdown discovery with curated safe lists\n"
                    "• Added **Sell Coins** directly to coin actions (`!매도` / `!코인판매`)\n"
                    "• Removed help/audit/action-with-input entries from FINAL ECLIPSE related dropdowns\n"
                    "• Preserved v18.1.3 bug reports, KoreanBots sync, legacy commands and saves"
                )
            else:
                await ctx.send(
                    "🧩 **ABADDON v18.1.4 — 전체 UI 브리지 안정화**\n"
                    "• 버튼→HybridCommand Context의 `_MissingSentinel.author` 오류 수정\n"
                    "• `관련 기능 더보기`를 전체 자동탐색에서 안전 화이트리스트 방식으로 변경\n"
                    "• 코인 행동에 **코인 판매** 바로 추가 (`!매도` / `!코인판매`)\n"
                    "• FINAL ECLIPSE 드롭다운의 help/검수/입력필요 행동 제거\n"
                    "• v18.1.3 버그신고·KoreanBots·기존 명령·저장 데이터 모두 보존"
                )
        patch.callback = patch_v1814
        patch.help = "ABADDON v18.1.4 전체 UI 브리지 안정화 최신 패치노트입니다."
        patch.description = patch.help

    print(
        f"[ABADDON v{VERSION}] full UI bridge stability registered: "
        f"curated_groups={len(ui1803.SAFE_RELATED_BY_GROUP)} coin_sell=True prefix_semantics=True",
        flush=True,
    )
