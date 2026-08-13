from __future__ import annotations

"""ABADDON v16.6.0 FIRST SURVIVAL & LIVE QA.

Additive quality-of-life and runtime-stability patch:
- turn the beginner guide into a resumable button-driven first-survival journey;
- attach state-aware recommendations to gameplay results;
- summarize actual gains, losses and unlocked progress after commands;
- consolidate prefix/UI incident data into a live QA center;
- audit economy, casino, gambling and relief settlement paths;
- explain major game terms without mixing Korean and English UI;
- preserve every legacy command and save-data key.
"""

import copy
import datetime as dt
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v600_game_center import _invoke_command
from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as hub
from apocalypse_bot.commands import v1650_survivor_core_complete as core1650

VERSION = "16.6.0"
ROOT_KEY = "v1660_first_survival"
MAX_RESULT_LINES = 7


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _locale(bot: commands.Bot, ctx_or_user: Any, guild_id: Optional[int] = None) -> str:
    user_id = int(getattr(getattr(ctx_or_user, "author", None), "id", 0) or getattr(ctx_or_user, "id", 0) or 0)
    gid = int(guild_id if guild_id is not None else getattr(getattr(ctx_or_user, "guild", None), "id", 0) or 0)
    try:
        from apocalypse_bot.commands import v1000_global_survivor as global_mod
        root = global_mod._RUNTIME.get("root", {})
        return global_mod._user_locale(root, user_id, gid)
    except Exception:
        return "ko"


def _safe_user(get_user: Callable[[int], Optional[MutableMapping[str, Any]]], user_id: int) -> Optional[MutableMapping[str, Any]]:
    row = get_user(int(user_id))
    return row if isinstance(row, MutableMapping) else None


def _state(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    row = user.setdefault(ROOT_KEY, {})
    if not isinstance(row, MutableMapping):
        row = {}
        user[ROOT_KEY] = row
    row.setdefault("tutorial_step", 0)
    row.setdefault("tutorial_completed", [])
    row.setdefault("result_summary", True)
    row.setdefault("smart_recommendations", True)
    row.setdefault("last_tutorial_at", 0)
    return row


def _is_admin(ctx: commands.Context) -> bool:
    member = getattr(ctx, "author", None)
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and (getattr(perms, "administrator", False) or getattr(perms, "manage_guild", False)))


@dataclass(frozen=True)
class TutorialStep:
    key: str
    title_ko: str
    title_en: str
    detail_ko: str
    detail_en: str
    command_candidates: Tuple[Tuple[str, str], ...]
    completion_names: Tuple[str, ...]
    emoji: str


TUTORIAL_STEPS: Tuple[TutorialStep, ...] = (
    TutorialStep(
        "register", "생존자 등록", "Register Survivor",
        "암시장 생존자 명부에 등록하고 초기 식량을 받습니다.",
        "Register as a survivor and receive starting supplies.",
        (("가입", "생존자"), ("register", "survivor")),
        ("가입", "register"), "🪪",
    ),
    TutorialStep(
        "profile", "내 정보 확인", "Check Your Profile",
        "체력·식량·직업·장비와 현재 생존 상태를 확인합니다.",
        "Review health, supplies, job, equipment and survival status.",
        (("정보", ""), ("profile", ""), ("생존허브", "")),
        ("정보", "profile", "생존허브", "survivorhub"), "👤",
    ),
    TutorialStep(
        "story", "시즌 1 시작", "Start Season 1",
        "메인 이야기 ‘검은 주파수’를 시작합니다. ABADDON의 중심 콘텐츠입니다.",
        "Begin Black Frequency, the main Season 1 story and core experience.",
        (("스토리 시작", ""), ("story start", ""), ("스토리", "시작")),
        ("스토리 시작", "story start", "스토리", "story"), "📖",
    ),
    TutorialStep(
        "field", "첫 폐허 탐색", "First Ruins Run",
        "파밍 지역을 열고 첫 현장 행동을 진행합니다.",
        "Open the farming regions and perform your first field action.",
        (("파밍", ""), ("farming", ""), ("지역탐색", ""), ("regionsearch", "")),
        ("파밍", "farming", "파밍출발", "지역탐색", "regionsearch"), "🧭",
    ),
    TutorialStep(
        "gear", "장비 확인", "Check Equipment",
        "현재 장비와 장착 가능한 생존 도구를 확인합니다.",
        "Review current equipment and available survival gear.",
        (("장비", ""), ("equipment", ""), ("가방", ""), ("bag", "")),
        ("장비", "equipment", "가방", "bag"), "🛡️",
    ),
    TutorialStep(
        "base", "기지 확인", "Check Your Base",
        "생존 기지의 단계·생산량·다음 건설 목표를 확인합니다.",
        "Review base level, production and the next construction goal.",
        (("기지", ""), ("base", ""), ("대피소", ""), ("shelter", "")),
        ("기지", "base", "대피소", "shelter"), "🏕️",
    ),
    TutorialStep(
        "today", "오늘 할 일", "Today's Tasks",
        "일일·주간 목표와 지금 가장 효율적인 다음 행동을 확인합니다.",
        "Review daily and weekly goals plus the best next action.",
        (("오늘할일", ""), ("today", ""), ("할일", "")),
        ("오늘할일", "today", "할일"), "🎯",
    ),
)


def _command_key(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    return str(getattr(command, "qualified_name", "") or getattr(command, "name", "") or "").strip()


def _resolve_step_command(bot: commands.Bot, step: TutorialStep, locale: str) -> Optional[Tuple[str, str]]:
    candidates = list(step.command_candidates)
    if locale == "en":
        candidates.sort(key=lambda pair: 0 if re.fullmatch(r"[A-Za-z0-9_ .-]+", pair[0]) else 1)
    for name, raw in candidates:
        command = bot.get_command(name)
        if command is not None:
            return command.qualified_name, raw
    return None


def _registered(user: Optional[Mapping[str, Any]]) -> bool:
    return isinstance(user, Mapping) and bool(user)


def _normalize_tutorial(user: Optional[MutableMapping[str, Any]]) -> int:
    if user is None:
        return 0
    state = _state(user)
    step = max(0, min(len(TUTORIAL_STEPS), int(state.get("tutorial_step", 0) or 0)))
    # Existing registered survivors should not be forced through registration again.
    if step == 0 and _registered(user):
        step = 1
        state["tutorial_step"] = step
        completed = state.setdefault("tutorial_completed", [])
        if isinstance(completed, list) and "register" not in completed:
            completed.append("register")
    return step


def _tutorial_embed(locale: str, user: Optional[MutableMapping[str, Any]], *, note: str = "") -> discord.Embed:
    step_index = _normalize_tutorial(user)
    total = len(TUTORIAL_STEPS)
    completed = step_index >= total
    title = _t(locale, "🌱 첫 생존자 여정", "🌱 First Survival Journey")
    description = _t(
        locale,
        "버튼만 따라가도 **가입 → 시즌 1 → 탐색 → 장비 → 기지**까지 이어집니다. 중간에 나가도 저장된 단계부터 계속합니다.",
        "Follow the buttons through **registration → Season 1 → exploration → gear → base**. Progress resumes after you leave.",
    )
    embed = discord.Embed(title=title, description=description, color=0x48C9B0 if not completed else 0x2ECC71)
    done_count = min(step_index, total)
    bar = "█" * done_count + "░" * (total - done_count)
    embed.add_field(name=_t(locale, "📊 진행도", "📊 Progress"), value=f"`{bar}` **{done_count}/{total}**", inline=False)
    lines: List[str] = []
    for idx, step in enumerate(TUTORIAL_STEPS):
        if idx < step_index:
            icon = "✅"
        elif idx == step_index:
            icon = "▶️"
        else:
            icon = "▫️"
        lines.append(f"{icon} {step.emoji} **{_t(locale, step.title_ko, step.title_en)}**")
    embed.add_field(name=_t(locale, "🧭 생존 경로", "🧭 Survival Route"), value="\n".join(lines), inline=False)
    if completed:
        embed.add_field(
            name=_t(locale, "🏆 첫 생존 완료", "🏆 First Survival Complete"),
            value=_t(locale, "이제 스토리 나침반과 생존 허브에서 현재 상황에 맞춰 계속 플레이하세요.", "Continue through Story Compass and Survivor Hub with state-aware guidance."),
            inline=False,
        )
    else:
        step = TUTORIAL_STEPS[step_index]
        embed.add_field(
            name=f"{step.emoji} {_t(locale, step.title_ko, step.title_en)}",
            value=_t(locale, step.detail_ko, step.detail_en),
            inline=False,
        )
    if note:
        embed.add_field(name=_t(locale, "ℹ️ 안내", "ℹ️ Note"), value=note[:1024], inline=False)
    embed.set_footer(text=_t(locale, "실행 결과에는 획득·변화·해금·다음 행동이 함께 표시됩니다.", "Results include gains, changes, unlocks and next actions."))
    return embed


class TutorialActionButton(discord.ui.Button):
    def __init__(self, owner: "FirstSurvivalView") -> None:
        self.owner_view = owner
        step_index = _normalize_tutorial(owner.user)
        completed = step_index >= len(TUTORIAL_STEPS)
        if completed:
            label = _t(owner.locale, "스토리 나침반", "Story Compass")
            emoji = "🧭"
        else:
            step = TUTORIAL_STEPS[step_index]
            label = _t(owner.locale, step.title_ko, step.title_en)
            emoji = step.emoji
        super().__init__(label=label[:80], emoji=emoji, style=discord.ButtonStyle.success, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        step_index = _normalize_tutorial(view.user)
        if step_index >= len(TUTORIAL_STEPS):
            target = view.bot.get_command("스토리나침반") or view.bot.get_command("storycompass")
            if target is None:
                await interaction.response.send_message(_t(view.locale, "스토리 나침반을 찾지 못했습니다.", "Story Compass was not found."), ephemeral=True)
                return
            pass  # v18.1.3: _invoke_command owns the single interaction ACK
            await _invoke_command(view.bot, interaction, target.qualified_name)
            return
        step = TUTORIAL_STEPS[step_index]
        resolved = _resolve_step_command(view.bot, step, view.locale)
        if resolved is None:
            await interaction.response.send_message(_t(view.locale, "이 단계의 기존 명령을 찾지 못했습니다. 운영자에게 검수를 요청해주세요.", "The linked command for this step was not found. Ask an admin to run the audit."), ephemeral=True)
            return
        name, raw = resolved
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        ok = await _invoke_command(view.bot, interaction, name, raw)
        if ok:
            view.user = view.get_user(interaction.user.id)
            _advance_tutorial(view.user, name, view.locale)
            view.save_data()
            view.refresh()
            try:
                if interaction.message is not None:
                    await interaction.message.edit(embed=_tutorial_embed(view.locale, view.user), view=view)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass


class TutorialNavButton(discord.ui.Button):
    def __init__(self, owner: "FirstSurvivalView", action: str, ko: str, en: str, emoji: str, row: int = 0) -> None:
        super().__init__(label=_t(owner.locale, ko, en), emoji=emoji, style=discord.ButtonStyle.secondary, row=row)
        self.owner_view = owner
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        if self.action == "hub":
            name = "생존허브" if view.locale == "ko" else "survivorhub"
        elif self.action == "commands":
            name = "명령어" if view.locale == "ko" else "help"
        elif self.action == "terms":
            name = "용어사전" if view.locale == "ko" else "glossary"
        elif self.action == "reset":
            if view.user is not None:
                state = _state(view.user)
                state["tutorial_step"] = 1 if _registered(view.user) else 0
                state["tutorial_completed"] = ["register"] if _registered(view.user) else []
                view.save_data()
            view.refresh()
            await interaction.response.edit_message(embed=_tutorial_embed(view.locale, view.user, note=_t(view.locale, "첫 생존 진행을 초기화했습니다.", "First Survival progress was reset.")), view=view)
            return
        else:
            return
        command = view.bot.get_command(name)
        if command is None:
            await interaction.response.send_message(_t(view.locale, "연결된 기능을 찾지 못했습니다.", "The linked feature was not found."), ephemeral=True)
            return
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        await _invoke_command(view.bot, interaction, command.qualified_name)


class FirstSurvivalView(discord.ui.View):
    def __init__(self, bot: commands.Bot, owner_id: int, locale: str, user: Optional[MutableMapping[str, Any]], get_user: Callable[[int], Optional[MutableMapping[str, Any]]], save_data: Callable[[], None]) -> None:
        super().__init__(timeout=900)
        self.bot = bot
        self.owner_id = int(owner_id)
        self.locale = locale
        self.user = user
        self.get_user = get_user
        self.save_data = save_data
        self.refresh()

    def refresh(self) -> None:
        self.clear_items()
        self.add_item(TutorialActionButton(self))
        self.add_item(TutorialNavButton(self, "hub", "생존 허브", "Survivor Hub", "👤", 0))
        self.add_item(TutorialNavButton(self, "commands", "전체 명령", "All Commands", "📚", 0))
        self.add_item(TutorialNavButton(self, "terms", "용어 설명", "Glossary", "❓", 1))
        self.add_item(TutorialNavButton(self, "reset", "진행 초기화", "Reset Progress", "♻️", 1))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.owner_id:
            return True
        await interaction.response.send_message(_t(self.locale, "본인의 첫 생존 패널을 열어주세요.", "Open your own First Survival panel."), ephemeral=True)
        return False


GLOSSARY: Dict[str, Tuple[str, str, str, str]] = {
    "스토리": ("📖", "시즌 1부터 이어지는 메인 아포칼립스 이야기입니다.", "The main apocalypse narrative beginning with Season 1.", "!스토리나침반"),
    "차원": ("🌀", "메인 진행 후 열리는 고위험 주간 탐험 세계입니다.", "A high-risk weekly exploration world unlocked later.", "!차원탐사"),
    "세력": ("🏴", "평판·영토·외교·전쟁을 공유하는 세계 조직입니다.", "World organizations with reputation, territory, diplomacy and wars.", "!세력"),
    "크루": ("🚀", "차원 임무와 우주선·공격대를 함께 진행하는 협동 조직입니다.", "A co-op group for dimension missions, ships and raids.", "!크루"),
    "연합망": ("🌐", "여러 서버·조직 활동을 연결해 공동 기록과 이벤트를 보여주는 시스템입니다.", "A network that links shared records and events across communities.", "!연합망"),
    "운명": ("✨", "선택과 행동이 누적되어 전설 카드와 사건 방향에 반영되는 성향입니다.", "A tendency shaped by choices and reflected in legends and events.", "!내전설"),
    "카지노": ("🎰", "포커·블랙잭·바카라·슬롯·VIP 등 카지노 테이블 콘텐츠입니다.", "Casino-table content such as poker, blackjack, baccarat, slots and VIP.", "!카지노"),
    "도박": ("🎲", "경마·탐색·주파수·생존 룰렛 등 카지노 밖의 배팅 콘텐츠입니다.", "Non-casino betting such as racing, exploration, frequency and survival roulette.", "!도박정보"),
    "도시공방": ("🎨", "제작한 도시 부품을 보관하고 지도에 배치·회전·레이어 조절하는 기능입니다.", "Store crafted city parts and place, rotate and layer them on the city map.", "!도시꾸미기"),
    "정부지원금": ("🏛️", "잔액이 -10,000 이하일 때 24시간마다 최대 250,000을 지원하는 재기 안전망입니다.", "A recovery safety net granting up to 250,000 every 24 hours when balance is -10,000 or lower.", "!정부지원금"),
}


def _normalize_term(value: str) -> str:
    return re.sub(r"[\s·_\-]+", "", str(value or "").casefold())


def _glossary_embed(locale: str, keyword: str = "") -> discord.Embed:
    token = _normalize_term(keyword)
    matched = [(name, data) for name, data in GLOSSARY.items() if not token or token in _normalize_term(name) or token in _normalize_term(data[1]) or token in _normalize_term(data[2])]
    embed = discord.Embed(
        title=_t(locale, "❓ ABADDON 생존 용어 사전", "❓ ABADDON Survival Glossary"),
        description=_t(locale, "처음 보는 기능 이름을 짧게 설명하고 바로 갈 명령을 표시합니다.", "Short explanations and direct commands for unfamiliar systems."),
        color=0x5B8FF9,
    )
    if not matched:
        embed.add_field(name=_t(locale, "검색 결과 없음", "No Match"), value=_t(locale, "다른 단어로 다시 검색하세요.", "Try another keyword."), inline=False)
    else:
        for name, (emoji, ko, en, command) in matched[:10]:
            label = name if locale == "ko" else {
                "스토리":"Story", "차원":"Dimensions", "세력":"Factions", "크루":"Crew", "연합망":"Alliance Network",
                "운명":"Fate", "카지노":"Casino", "도박":"Gambling", "도시공방":"City Workshop", "정부지원금":"Government Relief",
            }.get(name, name)
            embed.add_field(name=f"{emoji} {label}", value=f"{_t(locale, ko, en)}\n`{command}`", inline=False)
    return embed


def _mapping_numbers(value: Any) -> Dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    out: Dict[str, int] = {}
    for key, raw in value.items():
        if isinstance(raw, bool):
            continue
        try:
            out[str(key)] = int(raw)
        except (TypeError, ValueError):
            continue
    return out


def _item_names(value: Any) -> List[str]:
    if isinstance(value, Mapping):
        return [str(k) for k, v in value.items() if v]
    if isinstance(value, list):
        rows: List[str] = []
        for item in value:
            if isinstance(item, Mapping):
                rows.append(str(item.get("name") or item.get("id") or item.get("item") or "item"))
            else:
                rows.append(str(item))
        return rows
    return []


def _story_pointer(user: Mapping[str, Any]) -> str:
    try:
        command, label, _season, _state = core1650._story_target(user)
        return f"{command}|{label}"
    except Exception:
        return ""


def _snapshot(user: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(user, Mapping):
        return {"registered": False}
    return {
        "registered": True,
        "balance": int(user.get("balance", 0) or 0),
        "hp": int(user.get("hp", 100) or 100),
        "infection": int(user.get("infection", 0) or 0),
        "level": int(user.get("level", 1) or 1),
        "xp": int(user.get("xp", user.get("experience", 0)) or 0),
        "inventory": _item_names(user.get("inventory")),
        "equipment": _item_names(user.get("equipment")),
        "materials": _mapping_numbers(user.get("materials")),
        "resources": _mapping_numbers(user.get("resources")),
        "titles": _item_names(user.get("titles")),
        "story": _story_pointer(user),
        "base_level": int((user.get("base") or {}).get("level", user.get("base_level", 0)) if isinstance(user.get("base"), Mapping) else user.get("base_level", 0) or 0),
    }


def _multiset_delta(before: Sequence[str], after: Sequence[str]) -> Tuple[List[str], List[str]]:
    left = list(before)
    added: List[str] = []
    for item in after:
        if item in left:
            left.remove(item)
        else:
            added.append(item)
    return added, left


def _format_delta(value: int) -> str:
    return f"+{value:,}" if value > 0 else f"{value:,}"


def _diff(locale: str, before: Mapping[str, Any], after: Mapping[str, Any]) -> Tuple[List[str], List[str], List[str]]:
    gains: List[str] = []
    changes: List[str] = []
    unlocks: List[str] = []
    if not before.get("registered") and after.get("registered"):
        unlocks.append(_t(locale, "생존자 등록 완료 · 초기 RPG 기능 해금", "Survivor registered · core RPG unlocked"))
    numeric_labels = {
        "balance": ("식량", "Supplies"), "xp": ("경험치", "XP"), "level": ("레벨", "Level"),
        "hp": ("HP", "HP"), "infection": ("감염도", "Infection"), "base_level": ("기지 단계", "Base Level"),
    }
    for key, labels in numeric_labels.items():
        old = int(before.get(key, 0) or 0); new = int(after.get(key, 0) or 0)
        if old == new:
            continue
        delta = new - old
        label = _t(locale, labels[0], labels[1])
        changes.append(f"**{label}** {old:,} → {new:,} ({_format_delta(delta)})")
        if delta > 0 and key in {"balance", "xp", "level", "base_level"}:
            gains.append(f"{label} **{_format_delta(delta)}**")
    for field, labels in (("materials", ("재료", "Material")), ("resources", ("자원", "Resource"))):
        old_map = before.get(field) if isinstance(before.get(field), Mapping) else {}
        new_map = after.get(field) if isinstance(after.get(field), Mapping) else {}
        for key in sorted(set(old_map) | set(new_map)):
            delta = int(new_map.get(key, 0) or 0) - int(old_map.get(key, 0) or 0)
            if delta:
                line = f"**{key}** {_format_delta(delta)}"
                changes.append(line)
                if delta > 0:
                    gains.append(line)
    for field, labels in (("inventory", ("아이템", "Item")), ("equipment", ("장비", "Gear"))):
        added, removed = _multiset_delta(before.get(field, []) or [], after.get(field, []) or [])
        for item in added[:5]:
            gains.append(f"{_t(locale, labels[0], labels[1])} **{item}**")
        for item in removed[:5]:
            changes.append(f"{_t(locale, labels[0] + ' 사용/제거', labels[1] + ' used/removed')} **{item}**")
    added_titles, _removed_titles = _multiset_delta(before.get("titles", []) or [], after.get("titles", []) or [])
    for title in added_titles[:4]:
        unlocks.append(_t(locale, f"칭호 **{title}** 획득", f"Title **{title}** unlocked"))
    if before.get("story") != after.get("story") and after.get("story"):
        _command, _, label = str(after["story"]).partition("|")
        unlocks.append(_t(locale, f"스토리 목표 갱신: **{label}**", f"Story objective updated: **{label}**"))
    # Stable de-duplication and length control.
    gains = list(dict.fromkeys(gains))[:MAX_RESULT_LINES]
    changes = list(dict.fromkeys(changes))[:MAX_RESULT_LINES]
    unlocks = list(dict.fromkeys(unlocks))[:MAX_RESULT_LINES]
    return gains, changes, unlocks


def _has_equipment(user: Mapping[str, Any]) -> bool:
    return bool(_item_names(user.get("equipment")) or user.get("weapon") or user.get("armor"))


def _smart_actions(bot: commands.Bot, locale: str, user: Mapping[str, Any], command_name: str) -> List[Tuple[str, str, str, str, discord.ButtonStyle]]:
    actions: List[Tuple[str, str, str, str, discord.ButtonStyle]] = []
    def add(name: str, ko: str, en: str, emoji: str, style: discord.ButtonStyle = discord.ButtonStyle.secondary) -> None:
        command = bot.get_command(name)
        if command is None:
            return
        if any(row[0] == command.qualified_name for row in actions):
            return
        actions.append((command.qualified_name, ko, en, emoji, style))

    balance = int(user.get("balance", 0) or 0)
    hp = int(user.get("hp", 100) or 100)
    infection = int(user.get("infection", 0) or 0)
    target, _label, _season, _state = core1650._story_target(user)

    if command_name not in {"스토리나침반", "storycompass"}:
        add(target, "스토리 계속", "Continue Story", "📖", discord.ButtonStyle.success)
    if hp <= 40 or infection >= 60:
        add("휴식", "회복하기", "Recover", "❤️", discord.ButtonStyle.danger)
    if not _has_equipment(user):
        add("장비", "장비 확인", "Check Gear", "🛡️", discord.ButtonStyle.primary)
        add("상점", "상점", "Shop", "🛒")
    if balance <= -10_000:
        add("정부지원금", "정부지원금", "Government Relief", "🏛️", discord.ButtonStyle.success)
    lowered = command_name.casefold()
    if any(token in lowered for token in ("채집", "파밍", "낚시", "벌목", "광산", "gather", "farm")):
        add("가방", "가방", "Bag", "🎒")
        add("제작", "제작", "Craft", "🔨")
    if any(token in lowered for token in ("카지노", "포커", "블랙잭", "바카라", "casino", "poker", "blackjack", "baccarat")):
        add("카지노", "카지노 로비", "Casino Lobby", "🎰", discord.ButtonStyle.primary)
        add("게임전적", "전적", "Records", "📊")
    if any(token in lowered for token in ("도박", "경마", "룰렛", "gambling", "horse")):
        add("도박정보", "도박 안내", "Gambling Guide", "🎲", discord.ButtonStyle.primary)
        add("도박잔액", "도박 잔액", "Gambling Balance", "💰")
    if any(token in lowered for token in ("도시부품", "도시제작", "공방", "citypart", "workshop")):
        add("도시꾸미기", "바로 배치", "Place Part", "🎨", discord.ButtonStyle.success)
        add("도시지도", "도시지도", "City Map", "🏙️")
    add("오늘할일", "오늘 할 일", "Today", "🎯")
    add("생존허브", "생존 허브", "Survivor Hub", "👤", discord.ButtonStyle.primary)
    return actions[:10]


def _result_embed(locale: str, command_name: str, gains: Sequence[str], changes: Sequence[str], unlocks: Sequence[str], tutorial_note: str = "") -> discord.Embed:
    display = command_name if locale == "ko" else command_name
    embed = discord.Embed(
        title=_t(locale, "✅ 행동 결과 요약", "✅ Action Result Summary"),
        description=_t(locale, f"`!{display}` 실행 후 실제 저장 상태를 비교했습니다.", f"Compared saved state before and after `!{display}`."),
        color=0x27AE60,
    )
    if gains:
        embed.add_field(name=_t(locale, "🎁 이번 획득", "🎁 Gains"), value="\n".join(f"• {row}" for row in gains), inline=False)
    if changes:
        embed.add_field(name=_t(locale, "📊 변화", "📊 Changes"), value="\n".join(f"• {row}" for row in changes), inline=False)
    if unlocks:
        embed.add_field(name=_t(locale, "🔓 새로 열린 진행", "🔓 New Progress"), value="\n".join(f"• {row}" for row in unlocks), inline=False)
    if tutorial_note:
        embed.add_field(name=_t(locale, "🌱 첫 생존 진행", "🌱 First Survival Progress"), value=tutorial_note, inline=False)
    embed.set_footer(text=_t(locale, "수치 변화가 없으면 별도 결과 요약은 표시하지 않습니다.", "No extra summary is shown when saved state did not change."))
    return embed


def _advance_tutorial(user: Optional[MutableMapping[str, Any]], command_name: str, locale: str) -> str:
    if user is None:
        return ""
    state = _state(user)
    token = command_name.casefold()
    # Registration creates the user before command_completion is dispatched, so
    # handle it before the existing-user normalization advances step 0.
    if token in {"가입", "register"}:
        completed = state.setdefault("tutorial_completed", [])
        if isinstance(completed, list) and "register" not in completed:
            completed.append("register")
        if int(state.get("tutorial_step", 0) or 0) <= 1:
            state["tutorial_step"] = 1
            nxt = TUTORIAL_STEPS[1]
            return _t(locale, f"🪪 **생존자 등록 완료** → 다음: {nxt.emoji} **{nxt.title_ko}**", f"🪪 **Survivor registration complete** → Next: {nxt.emoji} **{nxt.title_en}**")
    index = _normalize_tutorial(user)
    if index >= len(TUTORIAL_STEPS):
        return ""
    step = TUTORIAL_STEPS[index]
    matches = any(token == name.casefold() or token.endswith(" " + name.casefold()) for name in step.completion_names)
    if not matches:
        return ""
    completed = state.setdefault("tutorial_completed", [])
    if isinstance(completed, list) and step.key not in completed:
        completed.append(step.key)
    state["tutorial_step"] = index + 1
    state["last_tutorial_at"] = int(time.time())
    if index + 1 >= len(TUTORIAL_STEPS):
        return _t(locale, "**첫 생존자 여정 완료!** 이제 스토리 나침반에서 계속 진행하세요.", "**First Survival Journey complete!** Continue through Story Compass.")
    nxt = TUTORIAL_STEPS[index + 1]
    return _t(locale, f"{step.emoji} **{step.title_ko} 완료** → 다음: {nxt.emoji} **{nxt.title_ko}**", f"{step.emoji} **{step.title_en} complete** → Next: {nxt.emoji} **{nxt.title_en}**")


def _incident_sources(world_data: Mapping[str, Any]) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]], Mapping[str, Any]]:
    ops = world_data.get("operations_v702") if isinstance(world_data.get("operations_v702"), Mapping) else {}
    incidents = ops.get("incidents") if isinstance(ops.get("incidents"), list) else []
    stats = ops.get("command_stats") if isinstance(ops.get("command_stats"), Mapping) else {}
    cute = world_data.get("v711_cute_interactions") if isinstance(world_data.get("v711_cute_interactions"), Mapping) else {}
    ui_errors = cute.get("ui_errors") if isinstance(cute.get("ui_errors"), list) else []
    return [x for x in incidents if isinstance(x, Mapping)], [x for x in ui_errors if isinstance(x, Mapping)], stats


def _live_qa_embed(locale: str, world_data: Mapping[str, Any], detailed: bool = False) -> discord.Embed:
    incidents, ui_errors, stats = _incident_sources(world_data)
    total_runs = sum(int((row or {}).get("runs", 0) or 0) for row in stats.values() if isinstance(row, Mapping))
    failures = sum(int((row or {}).get("failures", 0) or 0) for row in stats.values() if isinstance(row, Mapping))
    rate = failures / max(1, total_runs) * 100
    ranked = sorted(
        ((name, row) for name, row in stats.items() if isinstance(row, Mapping)),
        key=lambda pair: (int(pair[1].get("failures", 0) or 0), int(pair[1].get("runs", 0) or 0)),
        reverse=True,
    )
    embed = discord.Embed(
        title=_t(locale, "🛰️ ABADDON 실시간 오류센터", "🛰️ ABADDON Live QA Center"),
        description=_t(locale, "실제 실행 명령·버튼 UI·이미지/저장 오류 사건을 한 화면에서 확인합니다.", "Review runtime commands, component UI and image/save incidents in one place."),
        color=0xE67E22 if failures or ui_errors else 0x2ECC71,
    )
    embed.add_field(name=_t(locale, "📈 명령 실행", "📈 Command Runs"), value=f"{total_runs:,}", inline=True)
    embed.add_field(name=_t(locale, "🚨 명령 실패", "🚨 Failures"), value=f"{failures:,} ({rate:.2f}%)", inline=True)
    embed.add_field(name=_t(locale, "🧩 UI 사건", "🧩 UI Incidents"), value=f"{len(ui_errors):,}", inline=True)
    lines = []
    for name, row in ranked[:8]:
        fail = int(row.get("failures", 0) or 0)
        if fail <= 0:
            continue
        runs = int(row.get("runs", 0) or 0)
        lines.append(f"• `!{name}` · **{fail}/{runs}** · {str(row.get('last_error') or '-')[:80]}")
    embed.add_field(name=_t(locale, "반복 실패 명령", "Repeated Failures"), value="\n".join(lines) or _t(locale, "기록된 반복 실패 없음", "No repeated failures recorded"), inline=False)
    recent: List[str] = []
    for row in incidents[:5]:
        recent.append(f"• `{row.get('id','-')}` · `!{row.get('command','?')}` · {row.get('error_type','Error')}")
    for row in reversed(ui_errors[-5:]):
        recent.append(f"• `{row.get('id','-')}` · UI `{row.get('where','?')}` · {str(row.get('error','Error')).split(':',1)[0]}")
    embed.add_field(name=_t(locale, "최근 사건 번호", "Recent Incident IDs"), value="\n".join(recent[:10]) or _t(locale, "최근 사건 없음", "No recent incidents"), inline=False)
    if detailed:
        embed.add_field(
            name=_t(locale, "점검 항목", "Checks"),
            value=_t(locale, "명령 실패율 · 버튼/드롭다운 오류 · 이미지 생성 · 저장 · 응답 지연 · 반복 실패", "Command failure rate · components · image generation · saves · latency · repeated failures"),
            inline=False,
        )
    return embed


def _should_recommend(bot: commands.Bot, command_name: str) -> bool:
    blocked = {
        "명령어", "help", "초보생존", "firstsurvival", "초보센터", "beginnercenter",
        "용어사전", "glossary", "결과요약설정", "resultsummarysettings",
        "추천버튼설정", "recommendationsettings", "실시간오류센터", "liveqacenter",
        "경제정산검수", "economysettlementaudit", "1660통합검수", "v1660audit", "패치노트",
    }
    if command_name in blocked:
        return False
    index = getattr(bot, "v1630_command_index", {})
    entry = index.get(command_name) if isinstance(index, Mapping) else None
    if entry is None:
        return True
    return str(getattr(entry, "group", "")) not in {"help", "audit", "admin", "server_setup", "security", "alerts", "recovery"}


def register_v1660_first_survival_live_qa(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1660_registered", False):
        return
    bot._abaddon_v1660_registered = True
    bot.abaddon_version = VERSION

    async def send_tutorial(ctx: commands.Context) -> None:
        user = _safe_user(get_user, ctx.author.id)
        locale = _locale(bot, ctx)
        if user is not None:
            _normalize_tutorial(user)
            save_data()
        await ctx.send(embed=_tutorial_embed(locale, user), view=FirstSurvivalView(bot, ctx.author.id, locale, user, get_user, save_data))

    @bot.command(name="초보생존", aliases=["첫생존", "첫생존자여정", "firstsurvival", "survivorjourney"], help="버튼으로 가입·시즌 1·탐색·장비·기지까지 진행하고 중간 진행을 저장합니다.")
    async def first_survival(ctx: commands.Context) -> None:
        await send_tutorial(ctx)

    # Existing welcome panels and !명령어 beginner buttons already target !초보센터.
    # Keep that public entry point, but upgrade its callback to the resumable journey.
    beginner = bot.get_command("초보센터")
    if beginner is not None:
        async def beginner_callback(ctx: commands.Context) -> None:
            await send_tutorial(ctx)
        beginner.callback = beginner_callback
        beginner.help = "버튼만 따라가면 가입부터 시즌 1·탐색·장비·기지까지 이어지는 저장형 초보 여정입니다."
        beginner.description = beginner.help
        for alias in ("beginnercenter", "newcomerguide"):
            if alias not in beginner.aliases and bot.get_command(alias) is None:
                beginner.aliases.append(alias)
                bot.all_commands[alias] = beginner

    @bot.command(name="용어사전", aliases=["용어설명", "기능설명", "glossary", "termguide"], help="스토리·차원·세력·크루·카지노·도박 등 주요 용어를 짧게 설명합니다.")
    async def glossary(ctx: commands.Context, *, 검색어: str = "") -> None:
        await ctx.send(embed=_glossary_embed(_locale(bot, ctx), 검색어))

    @bot.command(name="결과요약설정", aliases=["행동결과설정", "resultsummarysettings", "resultsummary"], help="명령 완료 뒤 실제 획득·수치 변화·해금 요약을 켜거나 끕니다.")
    async def result_summary_settings(ctx: commands.Context, 설정: str = "") -> None:
        user = _safe_user(get_user, ctx.author.id)
        if user is None:
            await ctx.send(_t(_locale(bot, ctx), "먼저 `!가입 생존자`로 등록해주세요.", "Register first with `!register survivor`."))
            return
        state = _state(user)
        token = str(설정).strip().casefold()
        if token in {"켜기", "on", "enable", "true"}:
            state["result_summary"] = True
        elif token in {"끄기", "off", "disable", "false"}:
            state["result_summary"] = False
        save_data()
        enabled = bool(state.get("result_summary", True))
        await ctx.send(_t(_locale(bot, ctx), f"✅ 행동 결과 요약: **{'켜짐' if enabled else '꺼짐'}**", f"✅ Action result summaries: **{'ON' if enabled else 'OFF'}**"))

    @bot.command(name="추천버튼설정", aliases=["상황추천설정", "smartrecommendations", "recommendationsettings"], help="상태에 따라 달라지는 다음 행동 추천 버튼을 켜거나 끕니다.")
    async def recommendation_settings(ctx: commands.Context, 설정: str = "") -> None:
        user = _safe_user(get_user, ctx.author.id)
        if user is None:
            await ctx.send(_t(_locale(bot, ctx), "먼저 `!가입 생존자`로 등록해주세요.", "Register first with `!register survivor`."))
            return
        state = _state(user)
        token = str(설정).strip().casefold()
        if token in {"켜기", "on", "enable", "true"}:
            state["smart_recommendations"] = True
        elif token in {"끄기", "off", "disable", "false"}:
            state["smart_recommendations"] = False
        save_data()
        enabled = bool(state.get("smart_recommendations", True))
        await ctx.send(_t(_locale(bot, ctx), f"🧭 상황형 추천 버튼: **{'켜짐' if enabled else '꺼짐'}**", f"🧭 State-aware recommendations: **{'ON' if enabled else 'OFF'}**"))

    @bot.command(name="실시간오류센터", aliases=["라이브오류센터", "liveqacenter", "runtimeerrors"], help="실제 명령 실패·버튼 UI 사건·반복 오류와 사건 번호를 통합 표시합니다.")
    async def live_qa_center(ctx: commands.Context, 상세: str = "") -> None:
        if not _is_admin(ctx):
            await ctx.send(_t(_locale(bot, ctx), "🔒 서버 관리 권한이 필요합니다.", "🔒 Manage Server permission is required."))
            return
        await ctx.send(embed=_live_qa_embed(_locale(bot, ctx), world_data, bool(상세)))

    @bot.command(name="경제정산검수", aliases=["카지노정산검수", "economysettlementaudit", "casinosettlementaudit"], help="카지노·도박·경마·정부지원금의 정산·중복 지급·음수 잔액 안전망을 검사합니다.")
    async def economy_settlement_audit(ctx: commands.Context, 상세: str = "") -> None:
        required = ["카지노", "도박정보", "도박잔액", "경마장", "정부지원금", "게임전적"]
        checks: List[Tuple[str, bool, str]] = []
        for name in required:
            checks.append((f"!{name}", bot.get_command(name) is not None, _t(_locale(bot, ctx), "등록", "registered")))
        relief = bot.get_command("정부지원금")
        checks.append((_t(_locale(bot, ctx), "지원금 기준 -10,000", "Relief threshold -10,000"), bool(relief), "<= -10,000"))
        checks.append((_t(_locale(bot, ctx), "1회 상한 250,000", "Per-claim cap 250,000"), bool(relief), "250,000"))
        checks.append((_t(_locale(bot, ctx), "카지노/도박 메뉴 분리", "Casino/Gambling menu split"), any(e.group == "casino" for e in hub._build_registry(bot)) and any(e.group == "gambling" for e in hub._build_registry(bot)), "casino + gambling"))
        ops = world_data.get("operations_v702") if isinstance(world_data.get("operations_v702"), Mapping) else {}
        stats = ops.get("command_stats") if isinstance(ops.get("command_stats"), Mapping) else {}
        gambling_failures = sum(int(row.get("failures", 0) or 0) for name, row in stats.items() if isinstance(row, Mapping) and any(token in str(name) for token in ("카지노", "도박", "경마", "포커", "블랙잭", "바카라")))
        checks.append((_t(_locale(bot, ctx), "최근 정산 계열 실패", "Recent settlement failures"), gambling_failures == 0, str(gambling_failures)))
        ok = all(row[1] for row in checks)
        embed = discord.Embed(title=_t(_locale(bot, ctx), "🧾 경제·카지노 정산 검수", "🧾 Economy & Casino Settlement Audit"), color=0x2ECC71 if ok else 0xE67E22)
        embed.description = "\n".join(f"{'✅' if passed else '⚠️'} **{name}** · {detail}" for name, passed, detail in checks)
        if 상세:
            embed.add_field(name=_t(_locale(bot, ctx), "검수 원칙", "Audit Policy"), value=_t(_locale(bot, ctx), "판돈 1회 차감 · 결과 1회 정산 · 재시작 환불 · 음수 잔액 유지 · 지원금 쿨타임 기록", "Single stake debit · single settlement · restart refund · negative balance preserved · relief cooldown ledger"), inline=False)
        await ctx.send(embed=embed)

    # Replace the static v16.5 next-action listener to avoid duplicate panels.
    for listener in list(getattr(bot, "extra_events", {}).get("on_command_completion", []) or []):
        if getattr(listener, "__name__", "") == "v1650_next_actions":
            try:
                bot.remove_listener(listener, "on_command_completion")
            except Exception:
                pass

    @bot.listen("on_command")
    async def v1660_capture_before(ctx: commands.Context) -> None:
        try:
            user = _safe_user(get_user, ctx.author.id)
            setattr(ctx, "_v1660_before", _snapshot(user))
        except Exception:
            setattr(ctx, "_v1660_before", {"registered": False})

    @bot.listen("on_command_completion")
    async def v1660_result_and_guidance(ctx: commands.Context) -> None:
        try:
            if getattr(ctx.author, "bot", False):
                return
            command_name = _command_key(ctx)
            if not command_name:
                return
            user = _safe_user(get_user, ctx.author.id)
            if user is None:
                return
            locale = _locale(bot, ctx)
            state = _state(user)
            tutorial_note = _advance_tutorial(user, command_name, locale)
            before = getattr(ctx, "_v1660_before", _snapshot(user))
            after = _snapshot(user)
            gains, changes, unlocks = _diff(locale, before, after)
            if tutorial_note:
                save_data()
            if command_name in {"초보생존", "firstsurvival", "초보센터", "beginnercenter", "결과요약설정", "추천버튼설정", "실시간오류센터", "경제정산검수", "1660통합검수", "패치노트"}:
                return
            summary_enabled = bool(state.get("result_summary", True))
            recommendations_enabled = bool(state.get("smart_recommendations", True))
            recommend_now = recommendations_enabled and _should_recommend(bot, command_name)
            if not (gains or changes or unlocks or tutorial_note) and not recommend_now:
                return
            actions = _smart_actions(bot, locale, user, command_name) if recommend_now else []
            view = core1650.ActionView(bot, ctx.author.id, locale, actions) if actions else None
            if summary_enabled and (gains or changes or unlocks or tutorial_note):
                await ctx.send(embed=_result_embed(locale, command_name, gains, changes, unlocks, tutorial_note), view=view, delete_after=300)
            elif view is not None:
                await ctx.send(_t(locale, "🧭 **현재 상태에 맞는 다음 행동**", "🧭 **Recommended Next Actions**"), view=view, delete_after=180)
        except Exception as exc:
            print(f"[ABADDON v{VERSION} 결과/추천 경고] {type(exc).__name__}: {exc}", flush=True)

    @bot.command(name="1660통합검수", aliases=["v1660audit", "1660audit"], help="첫 생존 여정·결과 변화 요약·상황 추천·실시간 오류센터·경제 정산·용어 설명을 검사합니다.")
    async def audit_1660(ctx: commands.Context, 상세: str = "") -> None:
        required = [
            "초보생존", "초보센터", "용어사전", "결과요약설정", "추천버튼설정",
            "실시간오류센터", "경제정산검수", "스토리나침반", "생존허브", "명령어", "help",
        ]
        checks: List[Tuple[str, bool]] = [(name, bot.get_command(name) is not None) for name in required]
        checks.extend([
            ("튜토리얼 7단계", len(TUTORIAL_STEPS) == 7),
            ("한/영 단일 화면", all(step.title_ko and step.title_en for step in TUTORIAL_STEPS)),
            ("결과 스냅샷", callable(_snapshot) and callable(_diff)),
            ("상황형 추천", callable(_smart_actions)),
            ("기존 오류 장부 연결", isinstance(world_data.get("operations_v702", {}), Mapping)),
            ("카지노/도박 분리 유지", any(e.group == "casino" for e in hub._build_registry(bot)) and any(e.group == "gambling" for e in hub._build_registry(bot))),
        ])
        ok = all(value for _name, value in checks)
        locale = _locale(bot, ctx)
        embed = discord.Embed(title=_t(locale, "🧪 ABADDON v16.6.0 통합 검수", "🧪 ABADDON v16.6.0 Integration Audit"), color=0x2ECC71 if ok else 0xE74C3C)
        embed.description = "\n".join(f"{'✅' if value else '❌'} {name}" for name, value in checks)
        if 상세:
            incidents, ui_errors, stats = _incident_sources(world_data)
            embed.add_field(name=_t(locale, "실시간 장부", "Live Ledger"), value=f"commands {len(stats)} · incidents {len(incidents)} · UI {len(ui_errors)}", inline=False)
            embed.add_field(name=_t(locale, "보존 정책", "Preservation Policy"), value=_t(locale, "기존 명령·저장 키 삭제 0건 · v16.6 기능은 추가 계층", "0 legacy command/save-key deletions · v16.6 is additive"), inline=False)
        await ctx.send(embed=embed)

    # Latest patch-note command, localized without mixing languages.
    patch = bot.get_command("패치노트")
    if patch is not None:
        async def latest_patch(ctx: commands.Context) -> None:
            locale = _locale(bot, ctx)
            embed = discord.Embed(title=_t(locale, "📜 ABADDON v16.6.0 패치노트", "📜 ABADDON v16.6.0 Patch Notes"), color=0x5B2C9D)
            embed.add_field(name=_t(locale, "🌱 첫 생존자 여정", "🌱 First Survival Journey"), value=_t(locale, "가입→시즌 1→탐색→장비→기지→오늘 할 일을 버튼으로 진행하며 중간 단계를 저장합니다.", "A resumable button journey through registration, Season 1, exploration, gear, base and daily tasks."), inline=False)
            embed.add_field(name=_t(locale, "🎁 획득·변화 가시화", "🎁 Visible Gains & Changes"), value=_t(locale, "명령 전후 저장 상태를 비교해 획득, 소모, 수치 변화, 해금을 자동 요약합니다.", "Compares saved state before and after commands to summarize gains, costs, changes and unlocks."), inline=False)
            embed.add_field(name=_t(locale, "🧭 상황형 추천", "🧭 State-aware Guidance"), value=_t(locale, "체력·장비·부채·현재 콘텐츠에 따라 다음 버튼 구성이 달라집니다.", "Recommendations change with health, gear, debt and current activity."), inline=False)
            embed.add_field(name=_t(locale, "🛰️ 실시간 오류센터", "🛰️ Live QA Center"), value=_t(locale, "명령 실패·UI 사건·반복 오류·사건 번호를 통합했습니다.", "Unified command failures, UI incidents, repeated errors and incident IDs."), inline=False)
            embed.add_field(name=_t(locale, "🧾 경제 정산 안전", "🧾 Economy Settlement Safety"), value=_t(locale, "카지노·도박·경마·정부지원금 연결과 중복 정산 위험을 검사합니다.", "Audits casino, gambling, racing, relief and duplicate-settlement risks."), inline=False)
            embed.add_field(name=_t(locale, "❓ 용어 설명", "❓ Glossary"), value="`!용어사전` / `!glossary`", inline=False)
            embed.set_footer(text=_t(locale, "기존 명령·저장 데이터 삭제 0건 · v16.6.0", "0 legacy command or save-data deletions · v16.6.0"))
            await ctx.send(embed=embed)
        patch.callback = latest_patch
        patch.help = "ABADDON v16.6.0 첫 생존·상황 안내·결과 가시화·실시간 QA 최신 패치노트입니다."
        patch.description = patch.help

    # Rebuild live registry after all v16.6 commands are registered.
    entries = hub._build_registry(bot)
    setattr(bot, "v1630_command_entries", entries)
    setattr(bot, "v1630_command_index", {e.qualified_name: e for e in entries})

    class V1660CommandCenterView(hub.CompleteCommandCenterView):
        def __init__(self, owner_id: int, _legacy_guide: Sequence[Mapping[str, Any]], locale: str) -> None:
            super().__init__(owner_id, entries, locale, bot, get_user, save_data)

    ko_help = bot.get_command("명령어")
    if ko_help is not None:
        async def ko_callback(ctx: commands.Context, *, 검색어: str = None) -> None:
            view = V1660CommandCenterView(ctx.author.id, guide, "ko")
            if 검색어:
                rows = hub._search(entries, 검색어)
                if rows:
                    view.set_special(rows, f"🔎 전체 명령 검색 · {검색어}")
                    view.rebuild()
            await ctx.send(embed=view.current_embed(), view=view)
        ko_help.callback = ko_callback
        ko_help.help = "시즌 1 RPG부터 전체 명령을 탐색하고 처음 안내 버튼으로 저장형 첫 생존 여정을 시작합니다."
        ko_help.description = ko_help.help

    en_help = bot.get_command("help")
    if en_help is not None:
        async def en_callback(ctx: commands.Context, *, keyword: str = "") -> None:
            view = V1660CommandCenterView(ctx.author.id, guide, "en")
            if keyword:
                rows = hub._search(entries, keyword)
                if rows:
                    view.set_special(rows, f"🔎 Search All Commands · {keyword}")
                    view.rebuild()
            await ctx.send(embed=view.current_embed(), view=view)
        en_help.callback = en_callback
        en_help.help = "Browse every command in English-only UI and launch the resumable First Survival journey from Beginner."
        en_help.description = en_help.help

    guide.append({
        "id": "v1660_first_survival_live_qa",
        "emoji": "🌱",
        "title": "v16.6 FIRST SURVIVAL & LIVE QA",
        "hint": "저장형 초보 여정·획득/변화 결과·상황 추천·실시간 오류센터·경제 정산·용어 사전",
        "commands": [
            "!초보생존 · !초보센터 · !용어사전",
            "!결과요약설정 · !추천버튼설정",
            "!실시간오류센터 상세 · !경제정산검수 상세 · !1660통합검수 상세",
        ],
    })
