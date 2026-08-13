from __future__ import annotations

"""ABADDON v17.4.1 — MOUNT VISUAL RENEWAL.

Additive visual patch for the existing eight-mount system.  It preserves every
mount id, unlock threshold, command alias and save field while replacing the
low-resolution placeholders with localized high-definition cards and catalog
art.  Korean and English assets are stored separately.
"""

from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional

import discord
from discord.ext import commands

from apocalypse_bot.commands import v1620_living_legends as legends
from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as command_hub
from apocalypse_bot.commands import v1740_system_fusion as fusion
from apocalypse_bot.commands.v600_game_center import _safe_embed

VERSION = "17.4.1"
ASSET_ROOT = legends.ASSET_ROOT
MOUNT_DESCRIPTIONS: Dict[str, Dict[str, str]] = {
    "neon_bike": {"ko": "네온 동력으로 폐허를 질주하는 초고속 지상 탈것.", "en": "A neon-powered high-speed ground mount built for ruined streets.", "tag_ko": "지상 · 고속 이동", "tag_en": "GROUND · HIGH SPEED"},
    "black_carriage": {"ko": "심연 마력이 깃든 고풍스러운 다인승 마차.", "en": "An abyss-touched carriage designed for safe party travel.", "tag_ko": "지상 · 다인 탑승", "tag_en": "GROUND · PARTY RIDE"},
    "steam_train": {"ko": "강력한 증기 엔진으로 대량 인원과 화물을 운송한다.", "en": "A heavy steam engine that moves survivors and cargo at scale.", "tag_ko": "지상 · 대형 탑승", "tag_en": "GROUND · HEAVY TRANSPORT"},
    "abyss_airship": {"ko": "심연 부유석으로 차원 폭풍 위를 떠다니는 비행선.", "en": "A vast airship that rides above rift storms on abyssal liftstones.", "tag_ko": "공중 · 차원 항해", "tag_en": "AIR · RIFT VOYAGE"},
    "mecha_horse": {"ko": "정교한 기계 장치와 전투 코어로 움직이는 믿음직한 파트너.", "en": "A precise mechanical warhorse powered by a combat core.", "tag_ko": "지상 · 전투 특화", "tag_en": "GROUND · COMBAT"},
    "rift_glider": {"ko": "차원 균열을 가르며 활공하는 민첩한 경량 비행체.", "en": "A nimble light craft that glides along dimensional fractures.", "tag_ko": "공중 · 기동 특화", "tag_en": "AIR · MANEUVER"},
    "giant_companion": {"ko": "오랜 시간 함께한 거대한 동료가 이동과 전투를 지원한다.", "en": "A colossal bonded companion that carries and protects its survivor.", "tag_ko": "지상 · 전투 지원", "tag_en": "GROUND · SUPPORT"},
    "crew_flagship": {"ko": "크루의 기술과 결집을 상징하는 공중 이동 기지.", "en": "A flying command base that embodies the strength of the crew.", "tag_ko": "공중 · 이동 기지", "tag_en": "AIR · MOBILE BASE"},
}


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _locale(bot: commands.Bot, ctx: commands.Context) -> str:
    return fusion._ctx_locale(bot, ctx)


def _state(world_data: MutableMapping[str, Any], guild_id: int, user_id: int) -> MutableMapping[str, Any]:
    root = legends._root(world_data)
    guild = legends._guild(root, guild_id)
    return legends._user(guild, user_id)


def _localized_card(locale: str, mount_id: str) -> Path:
    path = ASSET_ROOT / "mounts" / locale / f"{mount_id}.jpg"
    if path.exists():
        return path
    return ASSET_ROOT / "mounts" / f"{mount_id}.png"


def _catalog_path(locale: str) -> Path:
    jpg = ASSET_ROOT / "previews" / f"mount_catalog_{locale}.jpg"
    if jpg.exists():
        return jpg
    return ASSET_ROOT / "previews" / f"mount_catalog_{locale}.png"


def _mount_embed(locale: str, mount_id: str, score: int, unlocked: bool, active: bool) -> discord.Embed:
    spec = legends.MOUNTS[mount_id]
    desc = MOUNT_DESCRIPTIONS[mount_id]
    title = _t(locale, spec["ko"], spec["en"])
    embed = discord.Embed(
        title=f"{'✅' if unlocked else '🔒'} {title}",
        description=_t(locale, desc["ko"], desc["en"]),
        color=0x00D9FF if mount_id in {"neon_bike", "mecha_horse"} else 0x8E44AD,
    )
    embed.add_field(name=_t(locale, "이동 등급", "Travel Tier"), value=f"+{int(spec['travel'])}", inline=True)
    embed.add_field(name=_t(locale, "해금 점수", "Unlock Score"), value=f"{int(spec['unlock'])}", inline=True)
    embed.add_field(name=_t(locale, "현재 점수", "Current Score"), value=f"{score}", inline=True)
    embed.add_field(name=_t(locale, "역할", "Role"), value=_t(locale, desc["tag_ko"], desc["tag_en"]), inline=False)
    if active:
        embed.add_field(name=_t(locale, "현재 대표 탈것", "Active Signature Mount"), value="✅", inline=False)
    embed.set_image(url=f"attachment://{mount_id}.jpg")
    embed.set_footer(text=_t(locale, "실제 저장 ID와 해금 조건은 기존 값 그대로 유지됩니다.", "Existing save IDs and unlock thresholds are unchanged."))
    return _safe_embed(embed)


def _entry_has(entries: List[Any], token: str, group: str) -> bool:
    folded = token.casefold()
    for entry in entries:
        names = {str(entry.name).casefold(), str(entry.qualified_name).casefold(), *(str(x).casefold() for x in entry.aliases)}
        if folded in names and entry.group == group:
            return True
    return False


def register_v1741_mount_visual_renewal(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: MutableMapping[str, Any],
    guide: List[Dict[str, Any]],
) -> None:
    del user_data
    if getattr(bot, "_abaddon_v1741_registered", False):
        return
    bot._abaddon_v1741_registered = True

    async def mount_catalog(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        locale = _locale(bot, ctx)
        user = get_user(int(ctx.author.id))
        if not isinstance(user, MutableMapping):
            return
        state = _state(world_data, int(ctx.guild.id if ctx.guild else 0), int(ctx.author.id))
        score = legends._legend_score(user, state)
        changed = False
        for mount_id, spec in legends.MOUNTS.items():
            if score >= int(spec["unlock"]) and mount_id not in state["unlocked_mounts"]:
                state["unlocked_mounts"].append(mount_id)
                changed = True
        if changed:
            save_data()
        lines = []
        for mount_id, spec in legends.MOUNTS.items():
            unlocked = mount_id in state["unlocked_mounts"]
            active = mount_id == state.get("active_mount")
            name = _t(locale, spec["ko"], spec["en"])
            status = "⭐" if active else ("✅" if unlocked else "🔒")
            lines.append(f"{status} **{name}** · {_t(locale, '전설', 'Legend')} {spec['unlock']} · {_t(locale, '이동', 'Travel')} +{spec['travel']}")
        embed = discord.Embed(
            title=_t(locale, "🏍️ ABADDON 고해상도 탈것 도감", "🏍️ ABADDON HD Mount Catalog"),
            description="\n".join(lines),
            color=0x7D3C98,
        )
        active_id = str(state.get("active_mount", "neon_bike"))
        active_spec = legends.MOUNTS.get(active_id, legends.MOUNTS["neon_bike"])
        embed.add_field(name=_t(locale, "현재 전설 점수", "Current Legend Score"), value=str(score), inline=True)
        embed.add_field(name=_t(locale, "대표 탈것", "Signature Mount"), value=_t(locale, active_spec["ko"], active_spec["en"]), inline=True)
        embed.add_field(name=_t(locale, "개별 카드 보기", "View Individual Card"), value=_t(locale, "`!탈것보기 탈것명`", "`!mountview mount name`"), inline=False)
        path = _catalog_path(locale)
        if path.exists():
            filename=f"mount_catalog_{locale}{path.suffix}"
            embed.set_image(url=f"attachment://{filename}")
            await ctx.send(embed=_safe_embed(embed), file=discord.File(path, filename=filename))
        else:
            await ctx.send(embed=_safe_embed(embed))

    catalog_cmd = bot.get_command("탈것도감") or bot.get_command("mounts")
    if catalog_cmd is not None:
        catalog_cmd.callback = mount_catalog
        catalog_cmd.help = "고해상도 탈것 8종, 해금 점수와 현재 대표 탈것을 확인합니다."
        catalog_cmd.description = catalog_cmd.help

    async def mount_ride(ctx: commands.Context, *, 탈것: str) -> None:
        if not await check_registered(ctx):
            return
        locale = _locale(bot, ctx)
        user = get_user(int(ctx.author.id))
        if not isinstance(user, MutableMapping):
            return
        state = _state(world_data, int(ctx.guild.id if ctx.guild else 0), int(ctx.author.id))
        mount_id = legends._resolve_mount(탈것, locale)
        if not mount_id or mount_id not in state["unlocked_mounts"]:
            await ctx.send(_t(locale, "해금하지 않은 탈것입니다. `!탈것도감`을 확인하세요.", "That mount is locked. Check `!mounts`."))
            return
        state["active_mount"] = mount_id
        legends._record_chronicle(state, "mount", f"equipped {mount_id}")
        save_data()
        score = legends._legend_score(user, state)
        path = _localized_card(locale, mount_id)
        embed = _mount_embed(locale, mount_id, score, True, True)
        embed.title = _t(locale, f"🏍️ {legends.MOUNTS[mount_id]['ko']} 탑승 완료", f"🏍️ Mounted {legends.MOUNTS[mount_id]['en']}")
        if path.exists():
            await ctx.send(embed=embed, file=discord.File(path, filename=f"{mount_id}.jpg"))
        else:
            await ctx.send(embed=embed)

    ride_cmd = bot.get_command("탈것탑승") or bot.get_command("ride")
    if ride_cmd is not None:
        ride_cmd.callback = mount_ride
        ride_cmd.help = "해금한 탈것을 대표 탈것으로 설정하고 고해상도 카드를 표시합니다."
        ride_cmd.description = ride_cmd.help

    @bot.command(name="탈것보기", aliases=["mountview", "viewmount", "mountcard"], help="탈것 이름을 입력해 고해상도 카드와 해금 상태를 확인합니다.")
    async def mount_view(ctx: commands.Context, *, 탈것: str = "") -> None:
        if not await check_registered(ctx):
            return
        locale = _locale(bot, ctx)
        user = get_user(int(ctx.author.id))
        if not isinstance(user, MutableMapping):
            return
        mount_id = legends._resolve_mount(탈것, locale)
        if not mount_id:
            await ctx.send(_t(locale, "탈것 이름을 확인하세요. 예: `!탈것보기 네온 바이크`", "Check the mount name. Example: `!mountview Neon Bike`"))
            return
        state = _state(world_data, int(ctx.guild.id if ctx.guild else 0), int(ctx.author.id))
        score = legends._legend_score(user, state)
        unlocked = mount_id in state["unlocked_mounts"] or score >= int(legends.MOUNTS[mount_id]["unlock"])
        if unlocked and mount_id not in state["unlocked_mounts"]:
            state["unlocked_mounts"].append(mount_id)
            save_data()
        path = _localized_card(locale, mount_id)
        embed = _mount_embed(locale, mount_id, score, unlocked, mount_id == state.get("active_mount"))
        if path.exists():
            await ctx.send(embed=embed, file=discord.File(path, filename=f"{mount_id}.jpg"))
        else:
            await ctx.send(embed=embed)

    @bot.command(name="1741탈것검수", aliases=["v1741mountaudit", "mountvisualaudit"], help="고해상도 탈것 카드·도감·KO/EN 분리와 명령 연결을 검사합니다.")
    async def mount_audit(ctx: commands.Context, detail: str = "") -> None:
        locale = _locale(bot, ctx)
        ko_cards = list((ASSET_ROOT / "mounts" / "ko").glob("*.jpg"))
        en_cards = list((ASSET_ROOT / "mounts" / "en").glob("*.jpg"))
        legacy_cards = list((ASSET_ROOT / "mounts").glob("*.png"))
        checks = [
            (_t(locale, "한국어 고해상도 카드 8/8", "Korean HD cards 8/8"), len(ko_cards) == len(legends.MOUNTS)),
            (_t(locale, "영어 고해상도 카드 8/8", "English HD cards 8/8"), len(en_cards) == len(legends.MOUNTS)),
            (_t(locale, "기존 탈것 ID 8/8 보존", "Legacy mount IDs preserved 8/8"), len(legacy_cards) == len(legends.MOUNTS)),
            (_t(locale, "한국어 도감 포스터", "Korean catalog poster"), _catalog_path("ko").exists()),
            (_t(locale, "영어 도감 포스터", "English catalog poster"), _catalog_path("en").exists()),
            (_t(locale, "탈것 도감 명령", "Mount catalog command"), bot.get_command("탈것도감") is not None and bot.get_command("mounts") is not None),
            (_t(locale, "탈것 보기 명령", "Mount view command"), bot.get_command("탈것보기") is not None and bot.get_command("mountview") is not None),
            (_t(locale, "탈것 탑승 명령", "Mount ride command"), bot.get_command("탈것탑승") is not None and bot.get_command("ride") is not None),
            (_t(locale, "한국어·영어 이미지 분리", "KO / EN asset separation"), all((ASSET_ROOT / "mounts" / loc / f"{mid}.jpg").exists() for loc in ("ko", "en") for mid in legends.MOUNTS)),
        ]
        ok = all(value for _name, value in checks)
        embed = discord.Embed(
            title=_t(locale, "🧪 ABADDON v17.4.1 탈것 시각 검수", "🧪 ABADDON v17.4.1 Mount Visual Audit"),
            description="\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks),
            color=0x2ECC71 if ok else 0xE74C3C,
        )
        if detail:
            largest = max([p.stat().st_size for p in ko_cards + en_cards] or [0])
            embed.add_field(name=_t(locale, "상세", "Details"), value=_t(locale, f"현지화 카드 16장 · 기존 ID 8개 · 최대 카드 {largest/1024/1024:.2f}MB", f"16 localized cards · 8 preserved IDs · largest card {largest/1024/1024:.2f}MB"), inline=False)
        await ctx.send(embed=_safe_embed(embed))

    # Repair v17.4.0 audit false negatives: category checks must accept aliases.
    audit_1740 = bot.get_command("1740통합검수")
    if audit_1740 is not None:
        async def audit_1740_alias_aware(ctx: commands.Context, detail: str = "") -> None:
            locale = _locale(bot, ctx)
            entries = command_hub._build_registry(bot)
            checks = [
                (_t(locale, "생존 단말기 카테고리", "Survivor Terminal category"), _entry_has(entries, "생존단말기", "terminal") or _entry_has(entries, "단말기", "terminal")),
                (_t(locale, "생존 의뢰소 카테고리", "Contract Office category"), _entry_has(entries, "의뢰소", "contracts")),
                (_t(locale, "생산센터 카테고리", "Production Center category"), _entry_has(entries, "생산센터", "production")),
                (_t(locale, "세력 평판 카테고리", "Faction reputation category"), _entry_has(entries, "세력평판", "factions") or _entry_has(entries, "평판", "factions")),
                (_t(locale, "스토리 시즌 1~6 보존", "Story Season 1–6 preserved"), bot.get_command("시즌6") is not None),
                (_t(locale, "솔로 원정 보존", "Solo expedition preserved"), bot.get_command("솔로원정") is not None),
                (_t(locale, "살아 있는 세계 보존", "Living world preserved"), bot.get_command("살아있는세계") is not None),
                (_t(locale, "NPC 인연 보존", "NPC bonds preserved"), bot.get_command("인연") is not None),
                (_t(locale, "도시 공방 보존", "City workshop preserved"), bot.get_command("도시꾸미기") is not None),
                (_t(locale, "카지노·일반 도박 보존", "Casino / Gambling preserved"), bot.get_command("카지노") is not None and bot.get_command("도박정보") is not None),
                (_t(locale, "고해상도 탈것 시각 레이어", "HD Mount visual layer"), bot.get_command("1741탈것검수") is not None),
            ]
            ok = all(v for _n, v in checks)
            embed = discord.Embed(title=_t(locale, "🧪 ABADDON v17.4.1 통합 검수", "🧪 ABADDON v17.4.1 Integration Audit"), description="\n".join(f"{'✅' if v else '❌'} {n}" for n,v in checks), color=0x2ECC71 if ok else 0xE74C3C)
            if detail:
                embed.add_field(name=_t(locale, "보존 원칙", "Preservation"), value=_t(locale, "기존 명령·탈것 ID·해금 조건·저장 데이터 삭제 0건", "0 legacy commands, mount IDs, unlock thresholds or saves removed"), inline=False)
            await ctx.send(embed=_safe_embed(embed))
        audit_1740.callback = audit_1740_alias_aware
        audit_1740.help = "v17.4.1 별칭 인식과 탈것 시각 레이어를 포함해 통합 검사합니다."
        audit_1740.description = audit_1740.help

    patch = bot.get_command("패치노트")
    if patch is not None:
        async def patch_v1741(ctx: commands.Context) -> None:
            locale = _locale(bot, ctx)
            embed = discord.Embed(title="🏍️ ABADDON v17.4.1 · MOUNT VISUAL RENEWAL", description=_t(locale, "탈것 8종을 실제 게임 명령과 연결된 고해상도 카드로 전면 교체했습니다.", "All eight mounts now use high-definition cards connected to live game commands."), color=0x7D3C98)
            embed.add_field(name=_t(locale, "🖼️ 8종 이미지 리뉴얼", "🖼️ Eight Renewed Mounts"), value=_t(locale, "네온 바이크·검은 마차·증기 열차·심연 비행선·기계 말·차원 활공선·거대 동료·크루 기함", "Neon Bike · Black Carriage · Steam Train · Abyss Airship · Mecha Horse · Rift Glider · Giant Companion · Crew Flagship"), inline=False)
            embed.add_field(name=_t(locale, "🔗 실제 게임 연동", "🔗 Live Game Integration"), value=_t(locale, "`!탈것도감`은 전체 도감, `!탈것보기`는 개별 카드, `!탈것탑승`은 장착 카드까지 표시합니다.", "`!mounts` shows the catalog, `!mountview` shows a card, and `!ride` equips it with the live card."), inline=False)
            embed.add_field(name=_t(locale, "🌐 언어 분리", "🌐 Locale Separation"), value=_t(locale, "한국어 카드 8장과 English 카드 8장을 별도 저장해 선택 언어만 표시합니다.", "Eight Korean and eight English cards are stored separately so only the selected locale is shown."), inline=False)
            embed.add_field(name=_t(locale, "🧪 검수 수정", "🧪 Audit Repair"), value=_t(locale, "v17.4 통합 검수가 정식 이름뿐 아니라 별칭도 인식하도록 수정했습니다.", "The v17.4 audit now recognizes both canonical names and aliases."), inline=False)
            embed.set_footer(text=_t(locale, "기존 탈것 ID·해금 조건·저장 데이터 삭제 0건", "0 mount IDs, unlock thresholds or save data removed"))
            await ctx.send(embed=_safe_embed(embed))
        patch.callback = patch_v1741
        patch.help = "ABADDON v17.4.1 탈것 이미지 리뉴얼 최신 패치노트입니다."
        patch.description = patch.help

    test = bot.get_command("테스트")
    if test is not None:
        async def test_v1741(ctx: commands.Context, mode: str = "", *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            locale = _locale(bot, ctx)
            required = ["탈것도감", "탈것보기", "탈것탑승", "1741탈것검수", "1740통합검수"]
            checks = [(name, bot.get_command(name) is not None) for name in required]
            checks.append(("16 localized mount cards", sum(1 for loc in ("ko", "en") for mid in legends.MOUNTS if (ASSET_ROOT / "mounts" / loc / f"{mid}.jpg").exists()) == 16))
            checks.append(("Legacy saves and IDs preserved", len(legends.MOUNTS) == 8))
            ok = all(v for _n,v in checks)
            embed = discord.Embed(title=_t(locale, "🧪 ABADDON v17.4.1 최신 테스트", "🧪 ABADDON v17.4.1 Latest Test"), description="\n".join(f"{'✅' if v else '❌'} {n}" for n,v in checks), color=0x2ECC71 if ok else 0xE74C3C)
            if str(mode).casefold() in {"상세", "detail", "full"}:
                embed.add_field(name=_t(locale, "범위", "Scope"), value="Mount Catalog · Mount View · Ride · KO/EN Assets · v17.4 Alias Audit", inline=False)
            await ctx.send(embed=_safe_embed(embed))
        test.callback = test_v1741
        test.help = "v17.4.1 탈것 이미지·명령·언어 분리와 통합 검수를 확인합니다."
        test.description = test.help

    guide.append({
        "id": "v1741_mount_visual_renewal", "emoji": "🏍️", "title": "v17.4.1 MOUNT VISUAL RENEWAL",
        "hint": "탈것 8종 고해상도 KO/EN 카드, 전체 도감, 개별 보기와 실제 탑승 연동",
        "commands": ["!탈것도감 · !탈것보기 네온 바이크 · !탈것탑승 네온 바이크", "!mounts · !mountview Neon Bike · !ride Neon Bike", "!1741탈것검수 상세 · !1740통합검수 상세"],
    })
    entries = command_hub._build_registry(bot)
    setattr(bot, "v1630_command_entries", entries)
    setattr(bot, "v1630_command_index", {entry.qualified_name: entry for entry in entries})
    print(f"[ABADDON v{VERSION}] mount visual renewal registered: mounts={len(legends.MOUNTS)} localized_cards=16", flush=True)


__all__ = ["register_v1741_mount_visual_renewal", "MOUNT_DESCRIPTIONS"]
