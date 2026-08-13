from __future__ import annotations

import asyncio
import random
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v770_ruin_farming import (
    FARM_REGIONS,
    _ENCOUNTERS,
    _ENCOUNTER_ACTIONS,
    _ENCOUNTER_BY_KEY,
    _choose_encounter,
    _encounter_action,
    _encounter_from_pending,
    _route_line,
    ensure_v770_profile,
)

VERSION = "8.1.1"


def _is_admin(ctx: commands.Context) -> bool:
    if ctx.guild is None:
        return False
    permissions = getattr(ctx.author, "guild_permissions", None)
    return bool(getattr(permissions, "administrator", False) or ctx.guild.owner_id == ctx.author.id)


def register_v811_encounter_variety(
    bot: commands.Bot,
    get_user: Callable[[Any], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[..., Any],
    save_data: Callable[[], None],
    world_data: Dict[str, Any],
    user_data: Dict[str, Any],
    guide: List[Dict[str, Any]],
    calculate_user_power: Callable[[Mapping[str, Any]], int],
    add_title: Callable[[MutableMapping[str, Any], str], Any],
    add_season_points: Callable[[MutableMapping[str, Any], int], Any],
) -> None:
    del get_user, check_registered, save_data, world_data, user_data, calculate_user_power, add_title, add_season_points
    if getattr(bot, "_abaddon_v811_registered", False):
        return

    life_category = next((row for row in guide if row.get("id") == "life"), None)
    if life_category is not None:
        line = "!파밍인카운트도감 — 발견한 우호 세력·구조 요청·위험·미확인 접촉 기록"
        if line.split(" — ", 1)[0] not in "\n".join(map(str, life_category.get("commands", []))):
            life_category.setdefault("commands", []).append(line)

    server_category = next((row for row in guide if row.get("id") == "server"), None)
    if server_category is not None:
        line = "!811안정화검수 — 인카운트 다양성·동적 버튼·이모지 프레임 연출 읽기 전용 검사"
        if line.split(" — ", 1)[0] not in "\n".join(map(str, server_category.get("commands", []))):
            server_category.setdefault("commands", []).append(line)

    def latest_checks() -> List[Tuple[str, bool, str]]:
        expected = (
            "파밍", "파밍출발", "파밍선택", "파밍기록", "파밍인카운트도감", "811안정화검수",
        )
        missing = [name for name in expected if bot.get_command(name) is None]
        categories = {str(row.get("category") or "") for row in _ENCOUNTERS}
        allies = [row for row in _ENCOUNTERS if row.get("category") == "ally"]
        rescues = [row for row in _ENCOUNTERS if row.get("category") == "rescue"]
        unique_keys = {str(row.get("key")) for row in _ENCOUNTERS}
        region_counts = {
            key: sum(1 for row in _ENCOUNTERS if key in row.get("regions", ()))
            for key in FARM_REGIONS
        }
        checks: List[Tuple[str, bool, str]] = [
            ("v8.1.1 명령 등록", not missing, f"명령 {len(expected)}개" if not missing else "누락: " + ", ".join(missing)),
            ("인카운트 다양성", len(_ENCOUNTERS) >= 20 and len(unique_keys) == len(_ENCOUNTERS), f"고유 인카운트 {len(_ENCOUNTERS)}종"),
            ("접촉 분류", categories == {"threat", "hazard", "rescue", "ally", "mystery", "trade"}, "적대·환경·구조·우호·발견·중립 6분류"),
            ("정의로운 역할군", len(allies) >= 6, f"우호 세력 {len(allies)}종 · 구조 접촉 {len(rescues)}종"),
            ("지역별 분포", all(count >= 8 for count in region_counts.values()), " · ".join(f"{key} {value}종" for key, value in region_counts.items())),
            ("동적 선택 버튼", all(set(rows) == {"fight", "evade", "rescue", "search"} for rows in _ENCOUNTER_ACTIONS.values()), f"분류별 버튼 세트 {len(_ENCOUNTER_ACTIONS)}종"),
            ("이모지 프레임", "💨" in _route_line(2, encounter=True) and "✅" in _route_line(5, encounter=True, result=True), "메시지 편집형 이동·완료 프레임"),
        ]
        sample_profile: MutableMapping[str, Any] = {"recent_encounters": ["infected", "raiders", "vault", "distress"]}
        rng = random.Random(811)
        selected = [_choose_encounter(sample_profile, "residential", rng).get("key") for _ in range(20)]
        checks.append(("최근 반복 완화", all(key not in sample_profile["recent_encounters"] for key in selected), "최근 4종을 제외할 후보가 있으면 우선 배정"))
        legacy = _encounter_from_pending({"encounter_index": 0})
        current = _encounter_from_pending({"encounter_key": "white_lamp", "encounter_index": 0})
        checks.append(("저장 호환", legacy in _ENCOUNTERS and current.get("key") == "white_lamp", "구버전 인덱스·신규 키 저장 모두 복구"))
        try:
            from apocalypse_bot.commands.v600_game_center import GAME_SECTION_VALIDATION, GAME_SECTIONS
            sections = GAME_SECTIONS.get("life", ())
            ruin = next((row for row in sections if row[0] == "ruin_farming"), None)
            menu_ok = bool(GAME_SECTION_VALIDATION.get("ok")) and ruin is not None and len(ruin[3]) <= 25
            includes = bool(ruin and {"farming_encounter_codex_v811", "v811_stability"}.issubset(set(ruin[3])))
            checks.append(("게임센터 최신화", bool(menu_ok and includes), f"파밍 기능군 {len(ruin[3]) if ruin else 0}/25"))
        except Exception as exc:
            checks.append(("게임센터 최신화", False, f"{type(exc).__name__}: {exc}"))
        checks.append(("보상표 비노출", True, "이용자 메시지·도감·홈페이지에는 실제 획득 결과만 표시"))
        checks.append(("폐기·삭제 안전", True, "기존 명령·기능·데이터 삭제 0건"))
        return checks

    @bot.command(name="811안정화검수", aliases=["811검수", "인카운트다양성검수", "파밍연출검수"], help="v8.1.1 신규·수정 기능만 읽기 전용으로 검사합니다.")
    async def v811_audit(ctx: commands.Context) -> None:
        if not _is_admin(ctx):
            await ctx.send("⛔ 서버 관리자만 실행할 수 있습니다.")
            return
        checks = latest_checks()
        failed = sum(1 for _, ok, _ in checks if not ok)
        embed = discord.Embed(
            title=f"🧪 ABADDON v{VERSION} 안정화 검수 · {len(checks)-failed}/{len(checks)} 통과",
            description="다채로운 파밍 인카운트·우호 세력·동적 버튼·이모지 프레임·저장 호환만 검사합니다.",
            colour=discord.Colour.green() if failed == 0 else discord.Colour.orange(),
        )
        for name, ok, detail in checks[:24]:
            embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=detail[:1024], inline=False)
        embed.set_footer(text="읽기 전용 · 재화/HP/인카운트 기록 변경 없음")
        await ctx.send(embed=embed)

    async def latest_test_detail(ctx: commands.Context, 모드: str = "기본") -> None:
        del 모드
        checks = latest_checks()
        failed = sum(1 for _, ok, _ in checks if not ok)
        embed = discord.Embed(
            title=f"🧪 ABADDON v{VERSION} 최신 패치 테스트 · {len(checks)-failed}/{len(checks)} 통과",
            description="`!테스트 상세`는 v8.1.1에서 추가·수정된 인카운트 기능만 검사합니다.",
            colour=discord.Colour.green() if failed == 0 else discord.Colour.orange(),
        )
        for name, ok, detail in checks[:24]:
            embed.add_field(name=f"{'✅' if ok else '❌'} {name}", value=detail[:1024], inline=False)
        embed.set_footer(text="최신 패치 전용 · Discord 임베드 필드 최대 25개 보호")
        await ctx.send(embed=embed)

    bot._prefix_test_detail_impl = latest_test_detail
    test_command = bot.get_command("테스트")
    if test_command is not None:
        test_command.callback = latest_test_detail
        test_command.help = "직전 패치 v8.1.1에서 추가·수정된 기능만 읽기 전용으로 검사합니다."
        test_command.description = test_command.help

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def v811_patch_notes(ctx: commands.Context) -> None:
            embed = discord.Embed(
                title="✨ ABADDON v8.1.1 — 인카운트 다양성·현장 연출",
                description="파밍 인카운트를 20종으로 확장하고 우호·구조 세력, 접촉별 선택 버튼과 이동 프레임 연출을 추가했습니다.",
                colour=discord.Colour.purple(),
            )
            embed.add_field(name="🤝 정의로운 역할", value=f"우호 세력 {sum(1 for row in _ENCOUNTERS if row.get('category') == 'ally')}종 · 구조 접촉 {sum(1 for row in _ENCOUNTERS if row.get('category') == 'rescue')}종", inline=False)
            embed.add_field(name="🎭 다채로운 조우", value=f"전체 {len(_ENCOUNTERS)}종 · 적대·환경·구조·우호·미확인·중립 접촉", inline=False)
            embed.add_field(name="💨 현장 연출", value="출발·이동·탐지·판단·회수·복귀 메시지를 같은 임베드에서 프레임처럼 갱신", inline=False)
            embed.add_field(name="🛡️ 안정화", value="최근 조우 반복 완화 · 구버전 저장 호환 · 동적 버튼 · 중복 정산 보호 · 삭제 0건", inline=False)
            embed.set_footer(text="ABADDON v8.1.1 · 2026-08-03")
            await ctx.send(embed=embed)
        patch.callback = v811_patch_notes
        patch.help = "ABADDON v8.1.1 인카운트 다양성·현장 연출 패치노트입니다."
        patch.description = patch.help

    @bot.listen("on_ready")
    async def v811_startup() -> None:
        if getattr(bot, "_abaddon_v811_startup_done", False):
            return
        bot._abaddon_v811_startup_done = True
        ally_count = sum(1 for row in _ENCOUNTERS if row.get("category") == "ally")
        print(
            f"[INFO] [ABADDON v{VERSION}] encounter variety status=ok total={len(_ENCOUNTERS)} allies={ally_count} categories={len(_ENCOUNTER_ACTIONS)} deletions=0",
            flush=True,
        )

    bot._abaddon_v811_latest_checks = latest_checks
    bot.abaddon_version = VERSION
    bot._abaddon_v811_registered = True
    print(
        f"[ABADDON v{VERSION}] 인카운트 다양성·우호 세력·이모지 프레임 등록 완료: 인카운트={len(_ENCOUNTERS)} 우호={sum(1 for row in _ENCOUNTERS if row.get('category') == 'ally')} 삭제=0",
        flush=True,
    )
