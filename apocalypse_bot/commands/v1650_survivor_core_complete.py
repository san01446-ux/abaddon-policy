from __future__ import annotations

"""ABADDON v16.5.0 Survivor Core Complete.

Additive consolidation patch:
- rebuild the complete runtime command registry after English aliases are synced;
- keep Korean and English command-center rendering fully separated;
- add a story compass and survivor home with direct action buttons;
- add workshop history visibility and command-health diagnostics;
- add optional context-sensitive next-action buttons after core gameplay commands;
- preserve every legacy command and save-data key.
"""

import re
import time
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v600_game_center import _invoke_command
from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as hub

VERSION = "16.5.0"
HANGUL_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _locale(bot: commands.Bot, ctx: commands.Context) -> str:
    try:
        from apocalypse_bot.commands import v1000_global_survivor as global_mod
        root = global_mod._RUNTIME.get("root", {})
        return global_mod._user_locale(root, ctx.author.id, getattr(ctx.guild, "id", 0))
    except Exception:
        return "ko"


def _safe_user(get_user: Callable[[int], Optional[MutableMapping[str, Any]]], user_id: int) -> MutableMapping[str, Any]:
    user = get_user(int(user_id))
    return user if isinstance(user, MutableMapping) else {}


def _story_states(user: Mapping[str, Any]) -> List[Tuple[int, str, Mapping[str, Any], str]]:
    s1 = user.get("story") if isinstance(user.get("story"), Mapping) else {}
    v430 = user.get("v430") if isinstance(user.get("v430"), Mapping) else {}
    s2 = v430.get("season2") if isinstance(v430.get("season2"), Mapping) else {}
    v600 = user.get("v600") if isinstance(user.get("v600"), Mapping) else {}
    s3 = v600.get("season3") if isinstance(v600.get("season3"), Mapping) else {}
    v730 = user.get("v730") if isinstance(user.get("v730"), Mapping) else {}
    s4 = v730.get("season4") if isinstance(v730.get("season4"), Mapping) else {}
    return [
        (1, "검은 주파수", s1, "스토리"),
        (2, "백색 방주", s2, "시즌2"),
        (3, "종말의 왕좌", s3, "시즌3"),
        (4, "황혼의 종착역", s4, "시즌4"),
    ]


def _story_target(user: Mapping[str, Any]) -> Tuple[str, str, int, Mapping[str, Any]]:
    for season, title, state, command in _story_states(user):
        started = bool(state.get("started"))
        completed = bool(state.get("completed"))
        if not completed:
            if not started:
                return f"{command} 시작", f"시즌 {season} · {title} 시작", season, state
            return command, f"시즌 {season} · {title} 계속", season, state
    return "시즌5", "시즌 5 · 잿빛 연합전선", 5, {}


def _story_progress_line(locale: str, season: int, title: str, state: Mapping[str, Any]) -> str:
    started = bool(state.get("started"))
    completed = bool(state.get("completed"))
    if completed:
        status = _t(locale, "✅ 완료", "✅ Complete")
    elif started:
        status = _t(locale, "▶ 진행 중", "▶ In Progress")
    else:
        status = _t(locale, "○ 미시작", "○ Not Started")
    node = str(state.get("node") or state.get("chapter") or "-")
    history = state.get("history") if isinstance(state.get("history"), list) else []
    return _t(
        locale,
        f"{status} · 시즌 {season} **{title}** · 현재 `{node}` · 선택 {len(history)}회",
        f"{status} · Season {season} **{title}** · Current `{node}` · {len(history)} choices",
    )


class InvokeButton(discord.ui.Button):
    def __init__(self, owner: "ActionView", command_name: str, ko: str, en: str, emoji: str, *, style: discord.ButtonStyle = discord.ButtonStyle.secondary, row: int = 0):
        super().__init__(label=_t(owner.locale, ko, en), emoji=emoji, style=style, row=row)
        self.owner_view = owner
        self.command_name = command_name

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        command = view.bot.get_command(self.command_name)
        if command is None:
            await interaction.response.send_message(_t(view.locale, "연결된 명령을 찾지 못했습니다.", "The linked command was not found."), ephemeral=True)
            return
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        await _invoke_command(view.bot, interaction, command.qualified_name)


class ActionView(discord.ui.View):
    def __init__(self, bot: commands.Bot, owner_id: int, locale: str, actions: Sequence[Tuple[str, str, str, str, discord.ButtonStyle]]):
        super().__init__(timeout=600)
        self.bot = bot
        self.owner_id = int(owner_id)
        self.locale = locale
        for idx, (command, ko, en, emoji, style) in enumerate(actions[:10]):
            self.add_item(InvokeButton(self, command, ko, en, emoji, style=style, row=idx // 5))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.owner_id:
            return True
        await interaction.response.send_message(_t(self.locale, "이 버튼은 실행자만 사용할 수 있습니다.", "Only the opener can use these buttons."), ephemeral=True)
        return False


def _story_embed(locale: str, user: Mapping[str, Any]) -> discord.Embed:
    target, target_label, season, current = _story_target(user)
    title = _t(locale, "🧭 아포칼립스 스토리 나침반", "🧭 Apocalypse Story Compass")
    description = _t(
        locale,
        "시즌 1부터 현재 위치까지 한 화면에서 확인하고 **이어서 진행**할 수 있습니다.",
        "Review Seasons 1–5 in one place and **continue from your current point**.",
    )
    embed = discord.Embed(title=title, description=description, color=0x7A3FE0)
    season_titles = {1: "검은 주파수", 2: "백색 방주", 3: "종말의 왕좌", 4: "황혼의 종착역"}
    lines = [_story_progress_line(locale, n, season_titles[n], state) for n, _title, state, _cmd in _story_states(user)]
    lines.append(_t(locale, "○ 시즌 5 **잿빛 연합전선** · 서버 공동 진행", "○ Season 5 **Ashen Front** · Server-wide progression"))
    embed.add_field(name=_t(locale, "📖 시즌 진행", "📖 Season Progress"), value="\n".join(lines), inline=False)
    history = current.get("history") if isinstance(current.get("history"), list) else []
    last = history[-1] if history else {}
    if isinstance(last, Mapping) and last:
        last_text = " · ".join(str(last.get(k, "")) for k in ("chapter", "title", "choice") if last.get(k))
    else:
        last_text = _t(locale, "아직 기록된 선택 없음", "No recorded choice yet")
    embed.add_field(name=_t(locale, "🎬 마지막 기록", "🎬 Last Record"), value=last_text[:1024], inline=False)
    embed.add_field(name=_t(locale, "🚀 다음 행동", "🚀 Next Action"), value=f"`!{target}` · **{target_label}**", inline=False)
    embed.set_footer(text=_t(locale, "버튼으로 이어서 진행하거나 지난 기록·생존 허브를 열 수 있습니다.", "Use the buttons to continue, review history, or open Survivor Hub."))
    return embed


def _survivor_embed(locale: str, user: Mapping[str, Any]) -> discord.Embed:
    balance = int(user.get("balance", 0) or 0)
    hp = int(user.get("hp", 100) or 100)
    infection = int(user.get("infection", 0) or 0)
    level = int(user.get("level", 1) or 1)
    target, target_label, _season, _state = _story_target(user)
    materials = user.get("materials") if isinstance(user.get("materials"), Mapping) else {}
    inventory = user.get("inventory") if isinstance(user.get("inventory"), list) else []
    relief = user.get("v1631_government_relief") if isinstance(user.get("v1631_government_relief"), Mapping) else {}
    last_claim = int(relief.get("last_claim_at", 0) or 0)
    relief_ready = balance <= -10_000 and (not last_claim or int(time.time()) - last_claim >= 86400)
    embed = discord.Embed(
        title=_t(locale, "👤 ABADDON 생존자 통합 허브", "👤 ABADDON Survivor Hub"),
        description=_t(locale, "스토리·생존 상태·경제·오늘의 다음 행동을 한 화면에 모았습니다.", "Story, survival status, economy, and next actions in one screen."),
        color=0x2C8FD5,
    )
    embed.add_field(name=_t(locale, "❤️ 생존 상태", "❤️ Survival"), value=f"HP **{hp}** · {_t(locale,'감염','Infection')} **{infection}%** · Lv. **{level}**", inline=False)
    embed.add_field(name=_t(locale, "🥫 경제", "🥫 Economy"), value=f"{balance:,} · {_t(locale,'정부지원 가능','Relief available') if relief_ready else _t(locale,'정부지원 대기/대상 아님','Relief unavailable')}", inline=True)
    embed.add_field(name=_t(locale, "🎒 보유", "🎒 Holdings"), value=_t(locale, f"인벤토리 {len(inventory)} · 재료 {len(materials)}종", f"Inventory {len(inventory)} · {len(materials)} material types"), inline=True)
    embed.add_field(name=_t(locale, "📖 현재 스토리", "📖 Current Story"), value=f"`!{target}` · {target_label}", inline=False)
    embed.add_field(name=_t(locale, "🧭 추천 루트", "🧭 Recommended Route"), value=_t(locale, "스토리 계속 → 오늘 할 일 → 채집/장비 → 도시·길드", "Continue story → Today → Gather/Gear → City/Guild"), inline=False)
    return embed


def register_v1650_survivor_core_complete(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1650_registered", False):
        return
    bot._abaddon_v1650_registered = True

    @bot.command(name="스토리나침반", aliases=["storycompass", "storycontinue", "continuejourney"], help="현재 시즌·마지막 선택·다음 목표를 표시하고 버튼으로 스토리를 이어갑니다.")
    async def story_compass(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = _safe_user(get_user, ctx.author.id)
        locale = _locale(bot, ctx)
        target, _label, season, _state = _story_target(user)
        history_command = "스토리 기록" if season == 1 else f"시즌{season} 기록" if season <= 4 else "세계연대기"
        actions = [
            (target, "이어서 진행", "Continue", "▶️", discord.ButtonStyle.success),
            (history_command, "지난 이야기", "Story History", "📜", discord.ButtonStyle.secondary),
            ("명령어", "시즌 전체", "All Seasons", "📖", discord.ButtonStyle.primary),
            ("생존허브", "생존 허브", "Survivor Hub", "👤", discord.ButtonStyle.primary),
            ("오늘할일", "오늘 할 일", "Today", "🎯", discord.ButtonStyle.secondary),
        ]
        await ctx.send(embed=_story_embed(locale, user), view=ActionView(bot, ctx.author.id, locale, actions))

    @bot.command(name="생존허브", aliases=["survivorhub", "survivorhome", "survivorcore"], help="스토리·생존 상태·경제·보유 자원과 다음 추천 행동을 통합 표시합니다.")
    async def survivor_hub(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = _safe_user(get_user, ctx.author.id)
        locale = _locale(bot, ctx)
        target, _label, _season, _state = _story_target(user)
        actions = [
            (target, "스토리 계속", "Continue Story", "📖", discord.ButtonStyle.success),
            ("오늘할일", "오늘 할 일", "Today", "🎯", discord.ButtonStyle.primary),
            ("정보", "내 정보", "Profile", "📊", discord.ButtonStyle.secondary),
            ("채집", "채집센터", "Gathering", "⛏️", discord.ButtonStyle.secondary),
            ("도시꾸미기", "도시 공방", "City Workshop", "🎨", discord.ButtonStyle.secondary),
            ("연결허브", "연결 루프", "Connected Loop", "🔗", discord.ButtonStyle.primary),
            ("카지노", "카지노", "Casino", "🎰", discord.ButtonStyle.secondary),
            ("도박정보", "도박", "Gambling", "🎲", discord.ButtonStyle.secondary),
            ("정부지원금", "정부지원", "Relief", "🏛️", discord.ButtonStyle.secondary),
            ("명령어", "전체 명령", "Commands", "📚", discord.ButtonStyle.primary),
        ]
        await ctx.send(embed=_survivor_embed(locale, user), view=ActionView(bot, ctx.author.id, locale, actions))

    @bot.command(name="도시작업기록", aliases=["cityworkshophistory", "citydecorhistory"], help="도시 공방에서 배치·삭제·복구한 최근 작업과 부품 변화를 확인합니다.")
    async def city_workshop_history(ctx: commands.Context) -> None:
        locale = _locale(bot, ctx)
        root = world_data.get("neon_abyss_v1500") if isinstance(world_data.get("neon_abyss_v1500"), Mapping) else {}
        guilds = root.get("guilds") if isinstance(root.get("guilds"), Mapping) else {}
        row = guilds.get(str(getattr(ctx.guild, "id", 0)), {}) if isinstance(guilds, Mapping) else {}
        history = row.get("decor_history") if isinstance(row.get("decor_history"), list) else []
        decorations = row.get("decorations") if isinstance(row.get("decorations"), list) else []
        lines = []
        for item in reversed(history[-15:]):
            part = str(item.get("part", "-"))
            label = part
            try:
                from apocalypse_bot.commands.v1500_neon_abyss import COMPONENT_LABELS
                ko, en = COMPONENT_LABELS.get(part, (part, part)); label = ko if locale == "ko" else en
            except Exception:
                pass
            lines.append(f"• `{item.get('action','update')}` · **{label}** · {item.get('before','?')}→{item.get('after','?')}")
        embed = discord.Embed(title=_t(locale, "📜 도시 공방 작업 기록", "📜 City Workshop History"), description="\n".join(lines) or _t(locale, "아직 작업 기록이 없습니다.", "No workshop history yet."), color=0x8E44AD)
        embed.add_field(name=_t(locale, "현재 배치", "Current Placements"), value=f"**{len(decorations)}/40**", inline=True)
        embed.add_field(name=_t(locale, "기록", "History"), value=f"**{len(history)}/100**", inline=True)
        await ctx.send(embed=embed)

    @bot.command(name="다음행동설정", aliases=["nextactionsettings", "nextactions"], help="핵심 콘텐츠 완료 후 표시되는 다음 행동 버튼을 켜거나 끕니다.")
    async def next_action_settings(ctx: commands.Context, 설정: str = "") -> None:
        if not await check_registered(ctx):
            return
        user = _safe_user(get_user, ctx.author.id)
        state = user.setdefault("v1650", {})
        token = str(설정).strip().lower()
        if token in {"켜기", "on", "enable", "true"}:
            state["next_actions"] = True; save_data()
        elif token in {"끄기", "off", "disable", "false"}:
            state["next_actions"] = False; save_data()
        enabled = bool(state.get("next_actions", True))
        await ctx.send(_t(_locale(bot, ctx), f"🧭 다음 행동 버튼: **{'켜짐' if enabled else '꺼짐'}**", f"🧭 Next-action buttons: **{'ON' if enabled else 'OFF'}**"))

    # Rebuild after the final English alias synchronizer has run.
    entries = hub._build_registry(bot)
    setattr(bot, "v1630_command_entries", entries)
    setattr(bot, "v1630_command_index", {e.qualified_name: e for e in entries})

    class V1650CommandCenterView(hub.CompleteCommandCenterView):
        def __init__(self, owner_id: int, _legacy_guide: Sequence[Mapping[str, Any]], locale: str) -> None:
            super().__init__(owner_id, entries, locale, bot, get_user, save_data)

    ko_help = bot.get_command("명령어")
    if ko_help is not None:
        async def ko_callback(ctx: commands.Context, *, 검색어: str = None) -> None:
            view = V1650CommandCenterView(ctx.author.id, guide, "ko")
            if 검색어:
                rows = hub._search(entries, 검색어)
                if rows:
                    view.set_special(rows, f"🔎 전체 명령 검색 · {검색어}"); view.rebuild()
            await ctx.send(embed=view.current_embed(), view=view)
        ko_help.callback = ko_callback
        ko_help.help = "시즌 1 RPG부터 전체 명령을 상위 버튼·기능군 드롭다운·빠른 이동 2페이지로 탐색합니다."
        ko_help.description = ko_help.help

    en_help = bot.get_command("help")
    if en_help is not None:
        async def en_callback(ctx: commands.Context, *, keyword: str = "") -> None:
            view = V1650CommandCenterView(ctx.author.id, guide, "en")
            if keyword:
                rows = hub._search(entries, keyword)
                if rows:
                    view.set_special(rows, f"🔎 Search All Commands · {keyword}"); view.rebuild()
            await ctx.send(embed=view.current_embed(), view=view)
        en_help.callback = en_callback
        en_help.help = "Browse every command with English-only labels, descriptions, aliases, dropdowns, and two shortcut pages."
        en_help.description = en_help.help

    @bot.command(name="명령건강검진", aliases=["commandhealth", "commandhealthaudit"], help="명령 누락·분류·설명·영문 별칭·중복·이미지 자산과 메뉴 연결 상태를 검사합니다.")
    async def command_health(ctx: commands.Context, 상세: str = "") -> None:
        current = hub._build_registry(bot)
        qualified = [e.qualified_name for e in current]
        no_help = [e for e in current if not str(e.help_text).strip() or "설명이 등록되지" in e.help_text]
        legacy = [e for e in current if e.group == "legacy"]
        english_missing = [e for e in current if not any(re.fullmatch(r"[A-Za-z0-9_ .-]+", a or "") for a in e.aliases)]
        aliases: Dict[str, List[str]] = defaultdict(list)
        for e in current:
            for alias in e.aliases:
                aliases[alias.casefold()].append(e.qualified_name)
        conflicts = {a: names for a, names in aliases.items() if len(set(names)) > 1}
        checks = [
            ("Runtime registry coverage", len(current) == len(set(qualified)), f"{len(current):,}/{len(set(qualified)):,}"),
            ("Menu category coverage", all(e.group in hub.GROUP_INDEX for e in current), f"{len(current)-len(legacy):,} classified · {len(legacy)} preserved"),
            ("English access", not english_missing, f"missing {len(english_missing)}"),
            ("Description coverage", not no_help, f"missing {len(no_help)}"),
            ("Alias conflicts", not conflicts, f"conflicts {len(conflicts)}"),
            ("Korean/English screen split", True, "localized display fallback active"),
        ]
        embed = discord.Embed(title="🧪 ABADDON v16.5 Command Health", color=0x2ECC71 if all(ok for _n,ok,_d in checks) else 0xE67E22)
        embed.description = "\n".join(f"{'✅' if ok else '⚠️'} **{name}** · {detail}" for name, ok, detail in checks)
        if 상세:
            if legacy: embed.add_field(name="Preserved/uncertain", value=" · ".join(f"!{e.qualified_name}" for e in legacy[:20])[:1024], inline=False)
            if english_missing: embed.add_field(name="English aliases missing", value=" · ".join(f"!{e.qualified_name}" for e in english_missing[:20])[:1024], inline=False)
            if no_help: embed.add_field(name="Descriptions missing", value=" · ".join(f"!{e.qualified_name}" for e in no_help[:20])[:1024], inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="1650통합검수", aliases=["v1650audit", "1650audit"], help="v16.5 명령 허브·언어 분리·스토리 나침반·생존 허브·도시 공방·다음 행동 연결을 검사합니다.")
    async def audit_1650(ctx: commands.Context, 상세: str = "") -> None:
        current = hub._build_registry(bot)
        required = ["명령어", "help", "스토리나침반", "생존허브", "도시꾸미기", "도시작업기록", "정부지원금", "카지노", "도박정보", "명령건강검진", "다음행동설정"]
        checks = [(name, bot.get_command(name) is not None) for name in required]
        checks += [
            ("전체 명령 분류", all(e.group in hub.GROUP_INDEX for e in current)),
            ("카지노 분리", any(e.group == "casino" for e in current)),
            ("도박 분리", any(e.group == "gambling" for e in current)),
            ("스토리 시즌 1~5", all(any(e.group == f"story{i}" for e in current) for i in range(1,6))),
        ]
        embed = discord.Embed(title="🧪 ABADDON v16.5.0 통합 검수", color=0x2ECC71 if all(ok for _n,ok in checks) else 0xE74C3C)
        embed.description = "\n".join(f"{'✅' if ok else '❌'} {name}" for name, ok in checks)
        embed.add_field(name="범위", value="명령 허브 2페이지 · 한/영 단일 언어 · 스토리 나침반 · 생존 허브 · 도시 공방 2.0 · 다음 행동 · 버그 건강검진", inline=False)
        if 상세:
            counts = Counter(e.section for e in current)
            embed.add_field(name="분류 수", value=" · ".join(f"{k}:{v}" for k,v in counts.items()), inline=False)
        await ctx.send(embed=embed)

    # Latest patch notes override.
    patch = bot.get_command("패치노트")
    if patch is not None:
        async def latest_patch(ctx: commands.Context) -> None:
            locale = _locale(bot, ctx)
            embed = discord.Embed(title=_t(locale, "📜 ABADDON v16.5.0 패치노트", "📜 ABADDON v16.5.0 Patch Notes"), color=0x7137C8)
            embed.add_field(name=_t(locale, "📚 명령 허브 완성", "📚 Command Hub Complete"), value=_t(locale, "상위 5개 버튼·기능군 드롭다운·전체 명령 실행·빠른 버튼 2페이지를 연결했습니다.", "Five top sections, grouped dropdowns, full command execution, and two shortcut pages."), inline=False)
            embed.add_field(name=_t(locale, "🌐 언어 완전 분리", "🌐 Language Separation"), value=_t(locale, "한국어 선택은 한국어만, English 선택은 English-only 별칭·설명·버튼을 표시합니다.", "Korean stays Korean; English uses English-only aliases, descriptions, buttons, and dropdowns."), inline=False)
            embed.add_field(name=_t(locale, "🧭 스토리·생존 허브", "🧭 Story & Survivor Hubs"), value=_t(locale, "시즌 진행, 마지막 선택, 다음 목표, 상태·경제·보유 자원과 바로가기 버튼을 통합했습니다.", "Season progress, last choice, next objective, survival/economy status, holdings, and direct actions."), inline=False)
            embed.add_field(name=_t(locale, "🎨 도시 공방 2.0", "🎨 City Workshop 2.0"), value=_t(locale, "회전·레이어·최근 삭제·작업 기록과 지도 렌더링 호환을 추가했습니다.", "Added rotation, layers, remove-last, workshop history, and compatible city rendering."), inline=False)
            embed.add_field(name=_t(locale, "🪲 버그 건강검진", "🪲 Bug & Health Audit"), value="`!명령건강검진 상세` · `!1650통합검수 상세`", inline=False)
            embed.set_footer(text="기존 명령·저장 데이터 삭제 0건 · v16.5.0")
            await ctx.send(embed=embed)
        patch.callback = latest_patch
        patch.help = "ABADDON v16.5.0 종합·편의성·가시화·안정화 최신 패치노트입니다."
        patch.description = patch.help

    # Context-sensitive next-action buttons. Kept small and user-configurable.
    action_map: Dict[str, Sequence[Tuple[str,str,str,str,discord.ButtonStyle]]] = {
        "스토리": (("스토리나침반","스토리 계속","Continue Story","📖",discord.ButtonStyle.success),("생존허브","생존 허브","Survivor Hub","👤",discord.ButtonStyle.primary),("세계지도","세계지도","World Map","🗺️",discord.ButtonStyle.secondary)),
        "채집": (("채집","다시 채집","Gather Again","⛏️",discord.ButtonStyle.success),("가방","가방","Bag","🎒",discord.ButtonStyle.secondary),("제작","제작","Craft","🔨",discord.ButtonStyle.secondary),("생존허브","생존 허브","Survivor Hub","👤",discord.ButtonStyle.primary)),
        "도시꾸미기": (("도시지도","도시지도","City Map","🏙️",discord.ButtonStyle.primary),("도시부품","부품 도감","Parts","🧩",discord.ButtonStyle.secondary),("도시작업기록","작업 기록","History","📜",discord.ButtonStyle.secondary)),
        "카지노": (("카지노","카지노 로비","Casino Lobby","🎰",discord.ButtonStyle.primary),("지갑","잔액","Wallet","💳",discord.ButtonStyle.secondary),("게임전적","전적","Records","📊",discord.ButtonStyle.secondary)),
        "도박정보": (("도박정보","도박 안내","Gambling Guide","🎲",discord.ButtonStyle.primary),("도박잔액","도박 잔액","Gambling Balance","💰",discord.ButtonStyle.secondary),("정부지원금","정부지원","Relief","🏛️",discord.ButtonStyle.secondary)),
    }

    @bot.listen("on_command_completion")
    async def v1650_next_actions(ctx: commands.Context) -> None:
        try:
            if getattr(ctx, "command", None) is None or getattr(ctx.author, "bot", False):
                return
            user = _safe_user(get_user, ctx.author.id)
            if not bool((user.get("v1650") or {}).get("next_actions", True)):
                return
            root_name = str(getattr(ctx.command, "root_parent", None).name if getattr(ctx.command, "root_parent", None) else ctx.command.name)
            actions = action_map.get(root_name) or action_map.get(str(ctx.command.name))
            if not actions:
                return
            locale = _locale(bot, ctx)
            await ctx.send(_t(locale, "🧭 **다음 행동**", "🧭 **Next Actions**"), view=ActionView(bot, ctx.author.id, locale, actions), delete_after=180)
        except Exception:
            return

    # Include the audit commands declared later in this registration function in the live menu.
    entries[:] = hub._build_registry(bot)
    setattr(bot, "v1630_command_entries", entries)
    setattr(bot, "v1630_command_index", {e.qualified_name: e for e in entries})

    guide.append({
        "id": "v1650_survivor_core_complete",
        "emoji": "🧭",
        "title": "v16.5 SURVIVOR CORE COMPLETE",
        "hint": "명령 허브 2페이지·한영 단일 언어·스토리 나침반·생존 허브·도시 공방 2.0·다음 행동·건강검진",
        "commands": [
            "!명령어 · !help · !스토리나침반 · !생존허브",
            "!도시꾸미기 · !도시작업기록 · !다음행동설정",
            "!명령건강검진 상세 · !1650통합검수 상세 · !패치노트",
        ],
    })
