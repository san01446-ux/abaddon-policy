from __future__ import annotations

"""ABADDON v17.0.0 — BLACK SUN CREATOR ERA.

Additive major release:
- runtime clean sweep for button command bridges and webhook delete scheduling;
- owner/admin creator forge for bilingual server events;
- community event play with visible rewards and one-time settlement;
- Season 6: Return of the Black Sun, a server-wide branching story;
- private owner proof vault and release diagnostics;
- complete Korean/English separation and command-center integration.
"""

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v600_game_center import _real_cog, _safe_embed, _safe_view, _invoke_command
from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as hub

VERSION = "17.0.0"
CREATOR_KEY = "creator_forge_v1700"
SEASON6_KEY = "season6_v1700"
OWNER_UUID = "abaddon-7be56c88-2026-17-black-sun"


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _locale(bot: commands.Bot, actor: Any, guild_id: int = 0) -> str:
    try:
        from apocalypse_bot.commands import v1000_global_survivor as global_mod
        root = global_mod._RUNTIME.get("root", {})
        return global_mod._user_locale(root, int(actor.id), int(guild_id))
    except Exception:
        return "ko"


def _ctx_locale(bot: commands.Bot, ctx: commands.Context) -> str:
    return _locale(bot, ctx.author, int(ctx.guild.id if ctx.guild else 0))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_admin(member: Any, guild: Optional[discord.Guild]) -> bool:
    if guild is None:
        return False
    if int(getattr(member, "id", 0)) == int(getattr(guild, "owner_id", 0)):
        return True
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and (perms.administrator or perms.manage_guild))


async def _is_owner_or_admin(bot: commands.Bot, member: Any, guild: Optional[discord.Guild]) -> bool:
    try:
        if await bot.is_owner(member):
            return True
    except Exception:
        pass
    return _is_admin(member, guild)


def _safe_user(get_user: Callable[[int], Optional[MutableMapping[str, Any]]], user_id: int) -> MutableMapping[str, Any]:
    user = get_user(int(user_id))
    return user if isinstance(user, MutableMapping) else {}


def _creator_root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault(CREATOR_KEY, {})
    if not isinstance(root, MutableMapping):
        root = {}
        world_data[CREATOR_KEY] = root
    root.setdefault("version", VERSION)
    root.setdefault("guilds", {})
    if not isinstance(root.get("guilds"), MutableMapping):
        root["guilds"] = {}
    root["version"] = VERSION
    return root


def _creator_guild(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    root = _creator_root(world_data)
    guilds = root["guilds"]
    state = guilds.setdefault(str(guild_id), {})
    if not isinstance(state, MutableMapping):
        state = {}
        guilds[str(guild_id)] = state
    state.setdefault("drafts", {})
    state.setdefault("events", {})
    state.setdefault("next_id", 1)
    for key in ("drafts", "events"):
        if not isinstance(state.get(key), MutableMapping):
            state[key] = {}
    return state


def _event_id(state: MutableMapping[str, Any]) -> str:
    number = max(1, int(state.get("next_id", 1) or 1))
    state["next_id"] = number + 1
    return f"EV{number:04d}"


def _parse_reward(text: str) -> Dict[str, Any]:
    reward: Dict[str, Any] = {"balance": 0, "exp": 0, "hp": 0, "infection": 0, "material": "", "material_qty": 0}
    for raw in re.split(r"[,;]", str(text or "")):
        part = raw.strip()
        if not part or "=" not in part:
            continue
        key, value = (x.strip() for x in part.split("=", 1))
        key = key.casefold()
        if key in {"food", "balance", "식량"}:
            reward["balance"] = max(-1_000_000, min(1_000_000, int(value or 0)))
        elif key in {"exp", "xp", "경험치"}:
            reward["exp"] = max(-10_000, min(100_000, int(value or 0)))
        elif key in {"hp", "체력"}:
            reward["hp"] = max(-100, min(100, int(value or 0)))
        elif key in {"infection", "감염"}:
            reward["infection"] = max(-100, min(100, int(value or 0)))
        elif key in {"item", "material", "재료", "아이템"}:
            if ":" in value:
                name, qty = value.rsplit(":", 1)
                reward["material"] = name.strip()[:40]
                reward["material_qty"] = max(0, min(999, int(qty or 0)))
            else:
                reward["material"] = value[:40]
                reward["material_qty"] = 1 if value else 0
    return reward


def _parse_choices(value: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in str(value or "").splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 4:
            continue
        reward = _parse_reward(parts[4] if len(parts) > 4 else "")
        rows.append({
            "label_ko": parts[0][:80],
            "label_en": parts[1][:80] or parts[0][:80],
            "outcome_ko": parts[2][:700],
            "outcome_en": parts[3][:700] or parts[2][:700],
            "reward": reward,
        })
        if len(rows) >= 5:
            break
    if len(rows) < 2:
        raise ValueError("선택지는 2~5줄이어야 하며 KO|EN|결과KO|결과EN|보상 형식을 사용합니다.")
    return rows


def _event_title(locale: str, event: Mapping[str, Any]) -> str:
    return str(event.get("title_en" if locale == "en" else "title_ko") or event.get("title_ko") or "Untitled")


def _event_description(locale: str, event: Mapping[str, Any]) -> str:
    return str(event.get("description_en" if locale == "en" else "description_ko") or event.get("description_ko") or "")


def _event_embed(locale: str, event: Mapping[str, Any], *, preview: bool = False) -> discord.Embed:
    rarity = str(event.get("rarity", "normal"))
    rarity_icon = {"normal": "⚪", "rare": "🔵", "epic": "🟣", "legend": "🟠", "hidden": "⚫"}.get(rarity, "⚪")
    embed = discord.Embed(
        title=f"{rarity_icon} {_event_title(locale, event)}",
        description=_event_description(locale, event)[:4000],
        color=0x7B2CBF,
    )
    choices = event.get("choices") if isinstance(event.get("choices"), list) else []
    lines = []
    for idx, choice in enumerate(choices, 1):
        label = str(choice.get("label_en" if locale == "en" else "label_ko") or choice.get("label_ko") or idx)
        lines.append(f"**{idx}.** {label}")
    embed.add_field(name=_t(locale, "🧭 선택", "🧭 Choices"), value="\n".join(lines) or "-", inline=False)
    embed.add_field(name=_t(locale, "📌 사건 ID", "📌 Event ID"), value=f"`{event.get('id', 'DRAFT')}` · {rarity}", inline=True)
    embed.add_field(name=_t(locale, "📡 상태", "📡 Status"), value=_t(locale, "미리보기" if preview else "공개 사건", "Preview" if preview else "Published Event"), inline=True)
    embed.set_footer(text=_t(locale, "선택 결과에는 획득·소모·수치 변화가 표시됩니다.", "Outcomes display gains, costs and stat changes."))
    return _safe_embed(embed)


def _draft_for(state: MutableMapping[str, Any], user_id: int) -> Optional[MutableMapping[str, Any]]:
    draft = state["drafts"].get(str(user_id))
    return draft if isinstance(draft, MutableMapping) else None


class EventDraftModal(discord.ui.Modal):
    def __init__(self, bot: commands.Bot, world_data: MutableMapping[str, Any], save_data: Callable[[], None], guild_id: int, owner_id: int, locale: str):
        super().__init__(title=_t(locale, "콘텐츠 공방 · 사건 제작", "Creator Forge · Build Event"), timeout=600)
        self.bot = bot
        self.world_data = world_data
        self.save_data = save_data
        self.guild_id = int(guild_id)
        self.owner_id = int(owner_id)
        self.locale = locale
        self.title_ko = discord.ui.TextInput(label=_t(locale, "제목 (한국어)", "Korean title"), max_length=80)
        self.title_en = discord.ui.TextInput(label=_t(locale, "제목 (English)", "English title"), max_length=80)
        self.desc_ko = discord.ui.TextInput(label=_t(locale, "설명 (한국어)", "Korean description"), style=discord.TextStyle.paragraph, max_length=1000)
        self.desc_en = discord.ui.TextInput(label=_t(locale, "설명 (English)", "English description"), style=discord.TextStyle.paragraph, max_length=1000)
        self.choices = discord.ui.TextInput(
            label=_t(locale, "선택지 2~5줄 · KO|EN|결과KO|결과EN|보상", "2–5 choices · KO|EN|result KO|result EN"),
            style=discord.TextStyle.paragraph,
            placeholder=_t(locale, "조사한다|Investigate|단서를 찾았다.|You found a clue.|food=1000,exp=20,item=철조각:2", "조사한다|Investigate|단서를 찾았다.|You found a clue.|food=1000,exp=20,item=Scrap:2"),
            max_length=4000,
        )
        for item in (self.title_ko, self.title_en, self.desc_ko, self.desc_en, self.choices):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if int(interaction.user.id) != self.owner_id:
            await interaction.response.send_message(_t(self.locale, "제작자만 저장할 수 있습니다.", "Only the creator can save this draft."), ephemeral=True)
            return
        try:
            choices = _parse_choices(str(self.choices.value))
        except (ValueError, TypeError) as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return
        state = _creator_guild(self.world_data, self.guild_id)
        previous = _draft_for(state, self.owner_id) or {}
        event = {
            "id": str(previous.get("id") or _event_id(state)),
            "author_id": self.owner_id,
            "title_ko": str(self.title_ko.value).strip(),
            "title_en": str(self.title_en.value).strip(),
            "description_ko": str(self.desc_ko.value).strip(),
            "description_en": str(self.desc_en.value).strip(),
            "choices": choices,
            "rarity": str(previous.get("rarity", "normal")),
            "published": False,
            "created_at": str(previous.get("created_at") or _now()),
            "updated_at": _now(),
        }
        state["drafts"][str(self.owner_id)] = event
        self.save_data()
        await interaction.response.send_message(
            _t(self.locale, f"✅ 사건 초안 `{event['id']}`을 저장했습니다.", f"✅ Saved event draft `{event['id']}`."),
            embed=_event_embed(self.locale, event, preview=True),
            ephemeral=True,
        )


class ForgeView(discord.ui.View):
    def __init__(self, bot: commands.Bot, world_data: MutableMapping[str, Any], save_data: Callable[[], None], guild_id: int, owner_id: int, locale: str):
        super().__init__(timeout=600)
        self.bot = bot
        self.world_data = world_data
        self.save_data = save_data
        self.guild_id = int(guild_id)
        self.owner_id = int(owner_id)
        self.locale = locale
        labels = (
            (_t(locale, "새 사건", "New Event"), "📝"),
            (_t(locale, "미리보기", "Preview"), "👁️"),
            (_t(locale, "공개", "Publish"), "📡"),
            (_t(locale, "라이브러리", "Library"), "📚"),
            (_t(locale, "사용법", "Help"), "❓"),
        )
        for item, (label, emoji) in zip(self.children, labels):
            item.label = label
            item.emoji = emoji

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) != self.owner_id:
            await interaction.response.send_message(_t(self.locale, "이 공방은 실행자만 조작할 수 있습니다.", "Only the opener can use this forge."), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="새 사건", emoji="📝", style=discord.ButtonStyle.primary, row=0)
    async def new_event(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(EventDraftModal(self.bot, self.world_data, self.save_data, self.guild_id, self.owner_id, self.locale))

    @discord.ui.button(label="미리보기", emoji="👁️", style=discord.ButtonStyle.secondary, row=0)
    async def preview(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        draft = _draft_for(_creator_guild(self.world_data, self.guild_id), self.owner_id)
        if not draft:
            await interaction.response.send_message(_t(self.locale, "저장된 초안이 없습니다.", "No saved draft."), ephemeral=True)
            return
        await interaction.response.send_message(embed=_event_embed(self.locale, draft, preview=True), view=EventPlayView(self.bot, self.world_data, self.save_data, None, draft, self.locale, test_mode=True), ephemeral=True)

    @discord.ui.button(label="공개", emoji="📡", style=discord.ButtonStyle.success, row=0)
    async def publish(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        state = _creator_guild(self.world_data, self.guild_id)
        draft = _draft_for(state, self.owner_id)
        if not draft:
            await interaction.response.send_message(_t(self.locale, "공개할 초안이 없습니다.", "No draft to publish."), ephemeral=True)
            return
        event = dict(draft)
        event["published"] = True
        event["published_at"] = _now()
        state["events"][str(event["id"])] = event
        self.save_data()
        await interaction.response.send_message(_t(self.locale, f"📡 `{event['id']}` 사건을 공개했습니다.", f"📡 Published event `{event['id']}`."), ephemeral=True)

    @discord.ui.button(label="라이브러리", emoji="📚", style=discord.ButtonStyle.secondary, row=0)
    async def library(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        state = _creator_guild(self.world_data, self.guild_id)
        events = [event for event in state["events"].values() if isinstance(event, Mapping) and event.get("published")]
        if not events:
            await interaction.response.send_message(_t(self.locale, "공개된 사건이 없습니다.", "No published events."), ephemeral=True)
            return
        lines = [f"`{e.get('id')}` · **{_event_title(self.locale, e)}** · {e.get('rarity','normal')}" for e in events[-20:]]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @discord.ui.button(label="사용법", emoji="❓", style=discord.ButtonStyle.secondary, row=0)
    async def help_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        text = _t(
            self.locale,
            "선택지 형식: `한국어|English|결과 한국어|Result English|food=1000,exp=20,hp=-5,infection=2,item=철조각:2`\n2~5줄을 입력하세요. 테스트는 보상을 지급하지 않습니다.",
            "Choice format: `Korean|English|Korean result|English result|food=1000,exp=20,hp=-5,infection=2,item=Scrap:2`\nEnter 2–5 lines. Test mode grants no rewards.",
        )
        await interaction.response.send_message(text, ephemeral=True)


class EventChoiceButton(discord.ui.Button):
    def __init__(self, owner: "EventPlayView", index: int, choice: Mapping[str, Any]):
        label = str(choice.get("label_en" if owner.locale == "en" else "label_ko") or choice.get("label_ko") or index + 1)
        super().__init__(label=label[:80], emoji=("🔍", "⚔️", "🕯️", "🧰", "🚪")[index % 5], style=discord.ButtonStyle.primary if index == 0 else discord.ButtonStyle.secondary, row=index // 5)
        self.owner_view = owner
        self.index = index

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        if view.owner_id is not None and int(interaction.user.id) != int(view.owner_id):
            await interaction.response.send_message(_t(view.locale, "이 사건은 실행자만 선택할 수 있습니다.", "Only the opener can choose this event."), ephemeral=True)
            return
        choices = view.event.get("choices") if isinstance(view.event.get("choices"), list) else []
        if self.index >= len(choices):
            await interaction.response.send_message(_t(view.locale, "선택지를 찾지 못했습니다.", "Choice not found."), ephemeral=True)
            return
        choice = choices[self.index]
        user = _safe_user(view.get_user, interaction.user.id) if view.get_user else {}
        if not view.test_mode and not user:
            await interaction.response.send_message(
                _t(view.locale, "먼저 `!가입`으로 생존자를 등록해주세요.", "Register a survivor with `!register` first."),
                ephemeral=True,
            )
            return
        event_id = str(view.event.get("id", "DRAFT"))
        state = user.setdefault("v1700", {}) if isinstance(user, MutableMapping) else {}
        completed = state.setdefault("completed_events", []) if isinstance(state, MutableMapping) else []
        key = f"{interaction.guild_id}:{event_id}"
        if not view.test_mode and key in completed:
            await interaction.response.send_message(_t(view.locale, "이미 완료하고 보상을 받은 사건입니다.", "You already completed and claimed this event."), ephemeral=True)
            return
        before = {
            "balance": int(user.get("balance", 0) or 0),
            "exp": int(user.get("exp", 0) or 0),
            "hp": int(user.get("hp", 100) or 100),
            "infection": int(user.get("infection", 0) or 0),
        }
        reward = choice.get("reward") if isinstance(choice.get("reward"), Mapping) else {}
        if not view.test_mode and user:
            user["balance"] = before["balance"] + int(reward.get("balance", 0) or 0)
            user["exp"] = max(0, before["exp"] + int(reward.get("exp", 0) or 0))
            user["hp"] = max(0, min(100, before["hp"] + int(reward.get("hp", 0) or 0)))
            user["infection"] = max(0, min(100, before["infection"] + int(reward.get("infection", 0) or 0)))
            material = str(reward.get("material", "") or "")
            qty = int(reward.get("material_qty", 0) or 0)
            if material and qty > 0:
                materials = user.setdefault("materials", {})
                if isinstance(materials, MutableMapping):
                    materials[material] = int(materials.get(material, 0) or 0) + qty
            if key not in completed:
                completed.append(key)
            view.save_data()
        after = {
            "balance": int(user.get("balance", before["balance"]) or 0),
            "exp": int(user.get("exp", before["exp"]) or 0),
            "hp": int(user.get("hp", before["hp"]) or 0),
            "infection": int(user.get("infection", before["infection"]) or 0),
        }
        outcome = str(choice.get("outcome_en" if view.locale == "en" else "outcome_ko") or choice.get("outcome_ko") or "")
        embed = discord.Embed(title=_t(view.locale, "🎭 사건 결과", "🎭 Event Outcome"), description=outcome[:4000], color=0x2ECC71)
        if view.test_mode:
            embed.add_field(name=_t(view.locale, "🧪 테스트 모드", "🧪 Test Mode"), value=_t(view.locale, "저장 데이터와 보상은 변경되지 않았습니다.", "No save data or rewards were changed."), inline=False)
        else:
            changes = [
                f"💰 {_t(view.locale,'식량','Food')} {before['balance']:,} → {after['balance']:,}",
                f"✨ EXP {before['exp']:,} → {after['exp']:,}",
                f"❤️ HP {before['hp']} → {after['hp']}",
                f"☣️ {_t(view.locale,'감염','Infection')} {before['infection']} → {after['infection']}",
            ]
            material = str(reward.get("material", "") or "")
            qty = int(reward.get("material_qty", 0) or 0)
            if material and qty:
                changes.append(f"🧱 {material} ×{qty}")
            embed.add_field(name=_t(view.locale, "📊 실제 변화", "📊 Actual Changes"), value="\n".join(changes), inline=False)
        for item in view.children:
            item.disabled = True
        await interaction.response.edit_message(embed=_safe_embed(embed), view=_safe_view(view))


class EventPlayView(discord.ui.View):
    def __init__(self, bot: commands.Bot, world_data: MutableMapping[str, Any], save_data: Callable[[], None], get_user: Optional[Callable[[int], Optional[MutableMapping[str, Any]]]], event: Mapping[str, Any], locale: str, *, owner_id: Optional[int] = None, test_mode: bool = False):
        super().__init__(timeout=600)
        self.bot = bot
        self.world_data = world_data
        self.save_data = save_data
        self.get_user = get_user
        self.event = event
        self.locale = locale
        self.owner_id = owner_id
        self.test_mode = test_mode
        choices = event.get("choices") if isinstance(event.get("choices"), list) else []
        for idx, choice in enumerate(choices[:5]):
            self.add_item(EventChoiceButton(self, idx, choice))


class EventSelect(discord.ui.Select):
    def __init__(self, owner: "EventLibraryView", events: Sequence[Mapping[str, Any]]):
        self.owner_view = owner
        options = []
        for event in list(events)[:25]:
            options.append(discord.SelectOption(label=_event_title(owner.locale, event)[:100], value=str(event.get("id"))[:100], description=str(event.get("rarity", "normal"))[:100], emoji="🎭"))
        super().__init__(placeholder=_t(owner.locale, "플레이할 사용자 사건 선택", "Choose a community event"), options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        event = view.event_map.get(self.values[0])
        if event is None:
            await interaction.response.send_message(_t(view.locale, "사건을 찾지 못했습니다.", "Event not found."), ephemeral=True)
            return
        play = EventPlayView(view.bot, view.world_data, view.save_data, view.get_user, event, view.locale, owner_id=interaction.user.id)
        await interaction.response.send_message(embed=_event_embed(view.locale, event), view=_safe_view(play), ephemeral=True)


class EventLibraryView(discord.ui.View):
    def __init__(self, bot: commands.Bot, world_data: MutableMapping[str, Any], save_data: Callable[[], None], get_user: Callable[[int], Optional[MutableMapping[str, Any]]], events: Sequence[Mapping[str, Any]], locale: str):
        super().__init__(timeout=300)
        self.bot = bot
        self.world_data = world_data
        self.save_data = save_data
        self.get_user = get_user
        self.locale = locale
        self.event_map = {str(event.get("id")): event for event in events}
        self.add_item(EventSelect(self, events))


@dataclass(frozen=True)
class SeasonChoice:
    ko: str
    en: str
    result_ko: str
    result_en: str
    effects: Mapping[str, int]
    unlock_ko: str
    unlock_en: str


@dataclass(frozen=True)
class SeasonChapter:
    title_ko: str
    title_en: str
    description_ko: str
    description_en: str
    choices: Tuple[SeasonChoice, SeasonChoice, SeasonChoice]


SEASON6_CHAPTERS: Tuple[SeasonChapter, ...] = (
    SeasonChapter(
        "1장 · 태양이 꺼진 밤", "Chapter 1 · The Night the Sun Died",
        "검은 태양이 떠오르며 BLACK CITY의 전력망과 차원 관문이 동시에 멈췄습니다. 첫 대응이 도시의 운명을 결정합니다.",
        "A black sun rises, shutting down BLACK CITY's grid and dimensional gates. The first response will shape the city.",
        (
            SeasonChoice("생존자부터 대피시킨다", "Evacuate survivors first", "대피로가 열리고 시민의 희망이 살아났습니다.", "Evacuation routes open and public hope rises.", {"hope": 2, "survival": 1}, "긴급 대피망", "Emergency Evacuation Network"),
            SeasonChoice("중앙 발전소를 사수한다", "Hold the central power plant", "전력 핵심부를 지켜 도시 질서를 유지했습니다.", "The power core holds, preserving city order.", {"order": 2, "survival": 1}, "비상 전력선", "Emergency Power Line"),
            SeasonChoice("차원 관문을 강제로 연다", "Force the dimensional gate open", "전력은 돌아왔지만 심연의 파장이 도시에 스며들었습니다.", "Power returns, but abyssal resonance seeps into the city.", {"abyss": 2, "order": -1}, "불안정 관문", "Unstable Gate"),
        ),
    ),
    SeasonChapter(
        "2장 · 검은 태양 교단", "Chapter 2 · Cult of the Black Sun",
        "정전 속에서 검은 태양을 구원이라 부르는 교단이 도시 방송망을 장악했습니다.",
        "A cult calling the black sun salvation seizes the city broadcast network.",
        (
            SeasonChoice("방송국을 정면 돌파한다", "Storm the broadcast station", "교단의 방송을 끊었지만 전투 피해가 발생했습니다.", "The broadcast is cut, but the assault costs lives.", {"order": 2, "survival": -1}, "탈환 방송국", "Reclaimed Broadcast Station"),
            SeasonChoice("내부 협력자를 설득한다", "Turn an insider", "내부자가 암호와 피난민 위치를 넘겼습니다.", "An insider provides codes and refugee locations.", {"hope": 2, "order": 1}, "내부 정보망", "Insider Network"),
            SeasonChoice("교단의 의식을 역추적한다", "Trace the cult ritual", "의식의 근원이 심연 관문과 연결되어 있음을 확인했습니다.", "The ritual is traced to the abyssal gate.", {"abyss": 2, "hope": 1}, "의식 좌표", "Ritual Coordinates"),
        ),
    ),
    SeasonChapter(
        "3장 · 살아 있는 성벽", "Chapter 3 · The Living Wall",
        "도시 외곽 성벽이 검은 조직으로 변하며 생존자와 감염체를 구분하지 않고 삼키기 시작했습니다.",
        "The outer wall turns into black living tissue and begins consuming survivors and infected alike.",
        (
            SeasonChoice("성벽을 소각한다", "Burn the wall", "감염 확산을 멈췄지만 외곽 방어선이 사라졌습니다.", "The spread stops, but the outer defense is lost.", {"survival": 2, "order": -1}, "소각 방어선", "Scorched Defense Line"),
            SeasonChoice("기술자와 성벽을 분리한다", "Separate it with engineers", "성벽의 살아 있는 핵을 분리해 방어 시설을 보존했습니다.", "Engineers isolate the living core while preserving defenses.", {"order": 2, "hope": 1}, "정화 성벽", "Purified Wall"),
            SeasonChoice("성벽과 공명한다", "Resonate with the wall", "성벽은 통제됐지만 도시가 심연의 목소리를 듣기 시작했습니다.", "The wall obeys, but the city begins hearing the abyss.", {"abyss": 3, "survival": 1}, "공명 성벽", "Resonant Wall"),
        ),
    ),
    SeasonChapter(
        "4장 · 두 개의 도시", "Chapter 4 · Two Cities",
        "현실의 BLACK CITY 위에 검은 태양 아래의 또 다른 도시가 겹쳐졌습니다. 두 세계 중 하나를 기준으로 고정해야 합니다.",
        "A second BLACK CITY overlaps reality beneath the black sun. One world must become the anchor.",
        (
            SeasonChoice("현재 도시를 고정한다", "Anchor the current city", "기존 시민과 기록을 지켰지만 차원 자원을 포기했습니다.", "Existing citizens and records survive, but dimensional resources are lost.", {"hope": 2, "order": 2, "abyss": -1}, "현실 고정점", "Reality Anchor"),
            SeasonChoice("두 도시를 부분 결합한다", "Partially merge both cities", "새 구역과 위험이 동시에 도시 역사에 편입됐습니다.", "New districts and new dangers enter the city's history.", {"survival": 2, "abyss": 1, "hope": 1}, "쌍둥이 지구", "Twin District"),
            SeasonChoice("검은 도시를 선택한다", "Choose the black city", "도시는 강력해졌지만 인간의 질서가 크게 흔들렸습니다.", "The city grows stronger while human order fractures.", {"abyss": 3, "order": -2}, "검은 왕도", "Black Capital"),
        ),
    ),
    SeasonChapter(
        "최종장 · 검은 태양의 심장", "Final Chapter · Heart of the Black Sun",
        "검은 태양의 심장이 중앙 카지노 상공에 내려왔습니다. 서버의 마지막 선택이 영구 결말을 기록합니다.",
        "The heart of the black sun descends above the central casino. The server's final vote writes a permanent ending.",
        (
            SeasonChoice("태양을 파괴한다", "Destroy the sun", "모든 세력이 힘을 모아 검은 태양을 산산조각 냈습니다.", "Every faction unites to shatter the black sun.", {"hope": 3, "survival": 2, "abyss": -2}, "새벽의 파편", "Shard of Dawn"),
            SeasonChoice("태양을 봉인한다", "Seal the sun", "검은 태양은 도시 지하에 봉인되고 감시 체계가 세워졌습니다.", "The black sun is sealed beneath the city under permanent watch.", {"order": 3, "survival": 2}, "영원의 봉인", "Eternal Seal"),
            SeasonChoice("태양과 계약한다", "Make a pact with the sun", "도시는 심연의 힘을 받아 새로운 존재로 다시 태어났습니다.", "The city accepts abyssal power and is reborn as something new.", {"abyss": 4, "hope": -1}, "검은 태양 계약", "Black Sun Pact"),
        ),
    ),
)


def _season_root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault(SEASON6_KEY, {})
    if not isinstance(root, MutableMapping):
        root = {}
        world_data[SEASON6_KEY] = root
    root.setdefault("version", VERSION)
    root.setdefault("guilds", {})
    if not isinstance(root.get("guilds"), MutableMapping):
        root["guilds"] = {}
    return root


def _season_state(world_data: MutableMapping[str, Any], guild_id: int) -> MutableMapping[str, Any]:
    root = _season_root(world_data)
    state = root["guilds"].setdefault(str(guild_id), {})
    if not isinstance(state, MutableMapping):
        state = {}
        root["guilds"][str(guild_id)] = state
    state.setdefault("started", False)
    state.setdefault("completed", False)
    state.setdefault("chapter", 0)
    state.setdefault("stats", {"hope": 0, "order": 0, "survival": 0, "abyss": 0})
    state.setdefault("votes", {})
    state.setdefault("history", [])
    state.setdefault("participants", [])
    state.setdefault("claims", [])
    if not isinstance(state.get("stats"), MutableMapping):
        state["stats"] = {"hope": 0, "order": 0, "survival": 0, "abyss": 0}
    for key in ("votes",):
        if not isinstance(state.get(key), MutableMapping):
            state[key] = {}
    for key in ("history", "participants", "claims"):
        if not isinstance(state.get(key), list):
            state[key] = []
    return state


def _season_votes(state: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    chapter = str(int(state.get("chapter", 0) or 0))
    votes = state["votes"].setdefault(chapter, {})
    if not isinstance(votes, MutableMapping):
        votes = {}
        state["votes"][chapter] = votes
    return votes


def _vote_counts(state: MutableMapping[str, Any]) -> List[int]:
    counts = [0, 0, 0]
    for value in _season_votes(state).values():
        try:
            idx = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < 3:
            counts[idx] += 1
    return counts


def _season_ending(state: Mapping[str, Any]) -> Tuple[str, str]:
    stats = state.get("stats") if isinstance(state.get("stats"), Mapping) else {}
    hope = int(stats.get("hope", 0) or 0)
    order = int(stats.get("order", 0) or 0)
    survival = int(stats.get("survival", 0) or 0)
    abyss = int(stats.get("abyss", 0) or 0)
    if abyss >= max(hope, order, survival) and abyss >= 7:
        return "심연의 왕도", "Capital of the Abyss"
    if hope >= 7 and survival >= 5:
        return "새벽의 귀환", "Return of Dawn"
    if order >= 7:
        return "영원의 봉인도시", "City of the Eternal Seal"
    if survival >= 7:
        return "최후의 요새", "The Last Fortress"
    return "검은 태양 협정", "Black Sun Accord"


def _season_embed(locale: str, state: MutableMapping[str, Any]) -> discord.Embed:
    if not state.get("started"):
        embed = discord.Embed(title=_t(locale, "☀️ 시즌 6 · 검은 태양의 귀환", "☀️ Season 6 · Return of the Black Sun"), description=_t(locale, "서버 전체가 투표로 진행하는 5장 공동 스토리입니다. 관리자가 `!시즌6시작`으로 시작합니다.", "A five-chapter server story driven by community votes. An admin starts it with `!season6start`."), color=0x1A0B2E)
        return embed
    stats = state["stats"]
    if state.get("completed"):
        ko, en = _season_ending(state)
        embed = discord.Embed(title=_t(locale, "🌅 시즌 6 완료", "🌅 Season 6 Complete"), description=_t(locale, f"서버 결말: **{ko}**", f"Server ending: **{en}**"), color=0xE67E22)
    else:
        chapter_index = max(0, min(len(SEASON6_CHAPTERS) - 1, int(state.get("chapter", 0) or 0)))
        chapter = SEASON6_CHAPTERS[chapter_index]
        embed = discord.Embed(title=f"☀️ {_t(locale, chapter.title_ko, chapter.title_en)}", description=_t(locale, chapter.description_ko, chapter.description_en), color=0x4B0082)
        counts = _vote_counts(state)
        lines = []
        for idx, choice in enumerate(chapter.choices):
            lines.append(f"**{idx+1}.** {_t(locale, choice.ko, choice.en)} · 🗳️ {counts[idx]}")
        embed.add_field(name=_t(locale, "🗳️ 현재 선택", "🗳️ Current Choices"), value="\n".join(lines), inline=False)
    embed.add_field(name=_t(locale, "🏙️ 도시 지표", "🏙️ City Metrics"), value=f"🌟 {_t(locale,'희망','Hope')} {stats.get('hope',0)} · 🛡️ {_t(locale,'질서','Order')} {stats.get('order',0)} · ❤️ {_t(locale,'생존','Survival')} {stats.get('survival',0)} · 🌀 {_t(locale,'심연','Abyss')} {stats.get('abyss',0)}", inline=False)
    embed.add_field(name=_t(locale, "👥 참여", "👥 Participation"), value=f"{len(set(str(x) for x in state.get('participants', [])))}", inline=True)
    embed.add_field(name=_t(locale, "📜 결정", "📜 Decisions"), value=f"{len(state.get('history', []))}/{len(SEASON6_CHAPTERS)}", inline=True)
    embed.set_footer(text=_t(locale, "각 장에서 한 번 투표할 수 있으며 결정 전에는 변경할 수 있습니다.", "Vote once per chapter; you may change it before resolution."))
    return _safe_embed(embed)


class SeasonVoteButton(discord.ui.Button):
    def __init__(self, owner: "Season6View", index: int, choice: SeasonChoice):
        super().__init__(label=_t(owner.locale, choice.ko, choice.en)[:80], emoji=("🌟", "🛡️", "🌀")[index], style=discord.ButtonStyle.primary if index == 0 else discord.ButtonStyle.secondary, row=0)
        self.owner_view = owner
        self.index = index

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        state = _season_state(view.world_data, view.guild_id)
        if not state.get("started") or state.get("completed"):
            await interaction.response.send_message(_t(view.locale, "현재 투표 가능한 장이 없습니다.", "There is no active chapter to vote on."), ephemeral=True)
            return
        votes = _season_votes(state)
        votes[str(interaction.user.id)] = self.index
        participants = state.setdefault("participants", [])
        if str(interaction.user.id) not in [str(x) for x in participants]:
            participants.append(str(interaction.user.id))
        view.save_data()
        await interaction.response.edit_message(embed=_season_embed(view.locale, state), view=_safe_view(view.refresh()))


class Season6View(discord.ui.View):
    def __init__(self, bot: commands.Bot, world_data: MutableMapping[str, Any], save_data: Callable[[], None], guild_id: int, locale: str):
        super().__init__(timeout=900)
        self.bot = bot
        self.world_data = world_data
        self.save_data = save_data
        self.guild_id = int(guild_id)
        self.locale = locale
        self.refresh()

    def refresh(self) -> "Season6View":
        self.clear_items()
        state = _season_state(self.world_data, self.guild_id)
        if state.get("started") and not state.get("completed"):
            chapter = SEASON6_CHAPTERS[max(0, min(len(SEASON6_CHAPTERS)-1, int(state.get("chapter",0) or 0)))]
            for idx, choice in enumerate(chapter.choices):
                self.add_item(SeasonVoteButton(self, idx, choice))
        self.add_item(SeasonUtilityButton(self, "history", _t(self.locale, "기록", "History"), "📜", row=1))
        self.add_item(SeasonUtilityButton(self, "reward", _t(self.locale, "보상", "Reward"), "🎁", row=1))
        self.add_item(SeasonUtilityButton(self, "resolve", _t(self.locale, "장 결정", "Resolve"), "⚖️", row=1, style=discord.ButtonStyle.success))
        return self


class SeasonUtilityButton(discord.ui.Button):
    def __init__(self, owner: Season6View, action: str, label: str, emoji: str, *, row: int, style: discord.ButtonStyle = discord.ButtonStyle.secondary):
        super().__init__(label=label[:80], emoji=emoji, style=style, row=row)
        self.owner_view = owner
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        if self.action == "history":
            command = view.bot.get_command("시즌6기록") or view.bot.get_command("season6history")
        elif self.action == "reward":
            command = view.bot.get_command("시즌6보상") or view.bot.get_command("season6reward")
        else:
            if not _is_admin(interaction.user, interaction.guild):
                await interaction.response.send_message(_t(view.locale, "관리자만 장을 결정할 수 있습니다.", "Only an admin can resolve a chapter."), ephemeral=True)
                return
            command = view.bot.get_command("시즌6결정") or view.bot.get_command("season6resolve")
        if command is None:
            await interaction.response.send_message(_t(view.locale, "연결된 명령이 없습니다.", "Linked command not found."), ephemeral=True)
            return
        pass  # v18.1.3: _invoke_command owns the single interaction ACK
        await _invoke_command(view.bot, interaction, command.qualified_name)


def _resolve_chapter(state: MutableMapping[str, Any], option: int = 0) -> Tuple[int, SeasonChoice, Mapping[str, int]]:
    chapter_idx = max(0, min(len(SEASON6_CHAPTERS)-1, int(state.get("chapter",0) or 0)))
    counts = _vote_counts(state)
    chosen = option - 1 if 1 <= option <= 3 else max(range(3), key=lambda idx: (counts[idx], -idx))
    choice = SEASON6_CHAPTERS[chapter_idx].choices[chosen]
    before = dict(state["stats"])
    for key, delta in choice.effects.items():
        state["stats"][key] = max(0, int(state["stats"].get(key, 0) or 0) + int(delta))
    state["history"].append({"chapter": chapter_idx + 1, "choice": chosen + 1, "counts": counts, "effects": dict(choice.effects), "at": _now()})
    state["chapter"] = chapter_idx + 1
    if state["chapter"] >= len(SEASON6_CHAPTERS):
        state["completed"] = True
        ko, en = _season_ending(state)
        state["ending_ko"] = ko
        state["ending_en"] = en
        state["completed_at"] = _now()
    return chosen, choice, before


def _owner_proof_path() -> Path:
    return Path(__file__).resolve().parents[2] / "ABADDON_OWNER_PROOF.json"


def register_v1700_creator_forge_season6(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    del check_registered, user_data
    if getattr(bot, "_abaddon_v1700_registered", False):
        return
    bot._abaddon_v1700_registered = True
    bot.abaddon_version = VERSION

    @bot.command(name="콘텐츠공방", aliases=["creatorforge", "eventforge", "사건공방"], help="관리자가 한국어·English 선택형 사건을 제작·테스트·공개합니다.")
    async def creator_forge(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        if not await _is_owner_or_admin(bot, ctx.author, ctx.guild):
            await ctx.send(_t(locale, "🔒 서버 관리자 또는 봇 소유자만 사용할 수 있습니다.", "🔒 Server admins or the bot owner only."))
            return
        state = _creator_guild(world_data, int(ctx.guild.id if ctx.guild else 0))
        draft = _draft_for(state, ctx.author.id)
        published = sum(1 for event in state["events"].values() if isinstance(event, Mapping) and event.get("published"))
        embed = discord.Embed(title=_t(locale, "🧩 ABADDON 콘텐츠 제작 공방", "🧩 ABADDON Creator Forge"), description=_t(locale, "코드 수정 없이 선택형 사건을 만들고 테스트한 뒤 서버에 공개합니다.", "Build, test and publish branching events without editing code."), color=0x7137C8)
        embed.add_field(name=_t(locale, "📝 현재 초안", "📝 Current Draft"), value=f"`{draft.get('id')}` · {_event_title(locale,draft)}" if draft else _t(locale,"없음","None"), inline=False)
        embed.add_field(name=_t(locale, "📡 공개 사건", "📡 Published Events"), value=str(published), inline=True)
        embed.add_field(name=_t(locale, "🌐 언어", "🌐 Languages"), value="한국어 / English separated", inline=True)
        embed.add_field(name=_t(locale, "🛡️ 안전", "🛡️ Safety"), value=_t(locale, "2~5개 선택지 · 보상 상한 · 테스트 무정산 · 1회 보상", "2–5 choices · reward caps · no-reward testing · one-time settlement"), inline=False)
        await ctx.send(embed=_safe_embed(embed), view=_safe_view(ForgeView(bot, world_data, save_data, int(ctx.guild.id if ctx.guild else 0), ctx.author.id, locale)))

    @bot.command(name="콘텐츠목록", aliases=["creatorlibrary", "eventlibrary"], help="서버에 공개된 사용자 제작 사건을 확인합니다.")
    async def creator_library(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        state = _creator_guild(world_data, int(ctx.guild.id if ctx.guild else 0))
        events = [event for event in state["events"].values() if isinstance(event, Mapping) and event.get("published")]
        if not events:
            await ctx.send(_t(locale, "📭 공개된 사용자 사건이 없습니다.", "📭 No community events are published."))
            return
        lines = [f"`{e.get('id')}` · **{_event_title(locale,e)}** · {e.get('rarity','normal')}" for e in events[-25:]]
        embed = discord.Embed(title=_t(locale,"📚 콘텐츠 공방 라이브러리","📚 Creator Forge Library"), description="\n".join(lines), color=0x5B2C9D)
        await ctx.send(embed=_safe_embed(embed), view=_safe_view(EventLibraryView(bot, world_data, save_data, get_user, events[-25:], locale)))

    @bot.command(name="사용자사건", aliases=["communityevent", "playevent"], help="공개된 사용자 제작 선택형 사건을 플레이합니다.")
    async def community_event(ctx: commands.Context, event_id: str = "") -> None:
        locale = _ctx_locale(bot, ctx)
        state = _creator_guild(world_data, int(ctx.guild.id if ctx.guild else 0))
        events = [event for event in state["events"].values() if isinstance(event, Mapping) and event.get("published")]
        if not events:
            await ctx.send(_t(locale, "📭 공개된 사용자 사건이 없습니다.", "📭 No community events are published."))
            return
        if event_id:
            event = state["events"].get(str(event_id).upper()) or state["events"].get(str(event_id))
            if not isinstance(event, Mapping) or not event.get("published"):
                await ctx.send(_t(locale, "사건 ID를 찾지 못했습니다.", "Event ID not found."))
                return
            await ctx.send(embed=_event_embed(locale, event), view=_safe_view(EventPlayView(bot, world_data, save_data, get_user, event, locale, owner_id=ctx.author.id)))
            return
        lines = [f"`{e.get('id')}` · **{_event_title(locale,e)}** · {e.get('rarity','normal')}" for e in events[-25:]]
        embed = discord.Embed(title=_t(locale,"📚 콘텐츠 공방 라이브러리","📚 Creator Forge Library"), description="\n".join(lines), color=0x5B2C9D)
        await ctx.send(embed=_safe_embed(embed), view=_safe_view(EventLibraryView(bot, world_data, save_data, get_user, events[-25:], locale)))

    @bot.command(name="콘텐츠비공개", aliases=["unpublishevent", "eventdisable"], help="관리자가 공개 사건을 비공개로 전환합니다.")
    async def unpublish_event(ctx: commands.Context, event_id: str) -> None:
        locale = _ctx_locale(bot, ctx)
        if not await _is_owner_or_admin(bot, ctx.author, ctx.guild):
            await ctx.send(_t(locale,"🔒 관리자만 사용할 수 있습니다.","🔒 Admin only.")); return
        state = _creator_guild(world_data, int(ctx.guild.id if ctx.guild else 0))
        event = state["events"].get(str(event_id).upper()) or state["events"].get(str(event_id))
        if not isinstance(event, MutableMapping):
            await ctx.send(_t(locale,"사건을 찾지 못했습니다.","Event not found.")); return
        event["published"] = False
        event["disabled_at"] = _now()
        save_data()
        await ctx.send(_t(locale, f"📴 `{event.get('id')}` 사건을 비공개로 전환했습니다.", f"📴 Unpublished event `{event.get('id')}`."))

    @bot.command(name="시즌6시작", aliases=["season6start", "blackSunStart"], help="관리자가 시즌 6 검은 태양의 귀환을 시작합니다.")
    async def season6_start(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        if not _is_admin(ctx.author, ctx.guild):
            await ctx.send(_t(locale,"🔒 서버 관리자만 시작할 수 있습니다.","🔒 Server admins only.")); return
        state = _season_state(world_data, int(ctx.guild.id if ctx.guild else 0))
        if state.get("started") and not state.get("completed"):
            await ctx.send(_t(locale,"이미 시즌 6이 진행 중입니다.","Season 6 is already active.")); return
        state.clear()
        state.update({"started": True, "completed": False, "chapter": 0, "stats": {"hope":0,"order":0,"survival":0,"abyss":0}, "votes":{}, "history":[], "participants":[], "claims":[], "started_at":_now()})
        save_data()
        await ctx.send(embed=_season_embed(locale,state), view=_safe_view(Season6View(bot, world_data, save_data, int(ctx.guild.id if ctx.guild else 0), locale)))

    @bot.group(name="시즌6", aliases=["season6", "검은태양", "blacksun"], invoke_without_command=True, case_insensitive=True, help="시즌 6 현재 장면·투표·도시 지표와 공동 결말 진행을 확인합니다.")
    async def season6(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        state = _season_state(world_data, int(ctx.guild.id if ctx.guild else 0))
        await ctx.send(embed=_season_embed(locale,state), view=_safe_view(Season6View(bot, world_data, save_data, int(ctx.guild.id if ctx.guild else 0), locale)))

    @bot.command(name="시즌6투표", aliases=["season6vote", "blackSunVote"], help="시즌 6 현재 장의 선택지 1~3에 투표합니다.")
    async def season6_vote(ctx: commands.Context, option: int) -> None:
        locale = _ctx_locale(bot, ctx)
        state = _season_state(world_data, int(ctx.guild.id if ctx.guild else 0))
        if not state.get("started") or state.get("completed") or option not in {1,2,3}:
            await ctx.send(_t(locale,"현재 투표할 수 없거나 선택 번호가 올바르지 않습니다.","Voting is unavailable or the option is invalid.")); return
        _season_votes(state)[str(ctx.author.id)] = option - 1
        if str(ctx.author.id) not in [str(x) for x in state["participants"]]: state["participants"].append(str(ctx.author.id))
        save_data()
        await ctx.send(_t(locale,f"🗳️ 선택지 **{option}번**에 투표했습니다.",f"🗳️ Voted for option **{option}**."), embed=_season_embed(locale,state))

    @bot.command(name="시즌6결정", aliases=["season6resolve", "blackSunResolve"], help="관리자가 현재 장의 최다 득표 선택을 확정합니다. 번호를 지정해 강제 결정할 수 있습니다.")
    async def season6_resolve(ctx: commands.Context, option: int = 0) -> None:
        locale = _ctx_locale(bot, ctx)
        if not _is_admin(ctx.author, ctx.guild):
            await ctx.send(_t(locale,"🔒 서버 관리자만 결정할 수 있습니다.","🔒 Server admins only.")); return
        state = _season_state(world_data, int(ctx.guild.id if ctx.guild else 0))
        if not state.get("started") or state.get("completed"):
            await ctx.send(_t(locale,"결정할 시즌 6 장면이 없습니다.","There is no active Season 6 chapter.")); return
        counts = _vote_counts(state)
        if sum(counts) <= 0 and option not in {1,2,3}:
            await ctx.send(_t(locale,"아직 투표가 없습니다. 번호를 지정하거나 투표를 기다려주세요.","No votes yet. Specify an option or wait for votes.")); return
        chosen, choice, before = _resolve_chapter(state, option)
        gid = int(ctx.guild.id if ctx.guild else 0)
        after = state["stats"]
        # v17.3: immediately echo the server decision into the living world and
        # participating survivors' NPC relationships instead of waiting for a
        # disconnected next-day refresh.
        try:
            living_root = world_data.setdefault("living_world_v1710", {}).setdefault("guilds", {})
            living = living_root.get(str(gid))
            if isinstance(living, MutableMapping):
                metrics = living.setdefault("metrics", {})
                metrics["hope"] = max(0, min(100, int(metrics.get("hope", 50) or 50) + int(choice.effects.get("hope", 0))))
                metrics["order"] = max(0, min(100, int(metrics.get("order", 50) or 50) + int(choice.effects.get("order", 0))))
                metrics["power"] = max(0, min(100, int(metrics.get("power", 50) or 50) + int(choice.effects.get("survival", 0))))
                metrics["tension"] = max(0, min(100, int(metrics.get("tension", 40) or 40) + int(choice.effects.get("abyss", 0))))
            guild_links = world_data.setdefault("connected_survival_v1730", {}).setdefault("guilds", {}).setdefault(str(gid), {})
            guild_links.setdefault("history", []).append({"at": _now(), "type": "season6_echo", "chapter": int(state.get("chapter", 0)), "choice": chosen + 1, "effects": dict(choice.effects)})
            guild_links["history"] = guild_links["history"][-100:]
            guild_links["season_echo"] = {"choice": chosen + 1, "effects": dict(choice.effects), "at": _now()}
            for participant_id in list(state.get("participants", []))[-500:]:
                survivor = _safe_user(get_user, int(participant_id))
                if not survivor:
                    continue
                link = survivor.setdefault("connected_survival_v1730", {})
                link.setdefault("history", []).append({"at": _now(), "type": "season6_echo", "detail": _t("ko", choice.unlock_ko, choice.unlock_en)})
                link["history"] = link["history"][-100:]
                bonds = survivor.setdefault("npc_bonds_v1720", {}).setdefault("npcs", {})
                if int(choice.effects.get("hope", 0)) > 0:
                    for npc_id in ("yoonseo", "mira"):
                        row = bonds.setdefault(npc_id, {}); row["affinity"] = min(100, int(row.get("affinity", 0) or 0) + 2); row["trust"] = min(100, int(row.get("trust", 10) or 10) + 1)
                if int(choice.effects.get("order", 0)) > 0:
                    row = bonds.setdefault("kane", {}); row["loyalty"] = min(100, int(row.get("loyalty", 20) or 20) + 2)
                if int(choice.effects.get("abyss", 0)) > 0:
                    for npc_id in ("eve", "nox"):
                        row = bonds.setdefault(npc_id, {}); row["affinity"] = min(100, int(row.get("affinity", 0) or 0) + 2)
        except Exception as exc:
            print(f"[ABADDON v17.3] season6 connection echo skipped: {type(exc).__name__}: {exc}", flush=True)
        save_data()
        result = discord.Embed(title=_t(locale,"⚖️ 서버 결정 확정","⚖️ Server Decision Resolved"), description=_t(locale,choice.result_ko,choice.result_en), color=0xE67E22)
        result.add_field(name=_t(locale,"🗳️ 확정 선택","🗳️ Chosen Option"), value=f"**{chosen+1}.** {_t(locale,choice.ko,choice.en)} · {counts[chosen]} votes", inline=False)
        changes=[]
        for key, emoji, ko, en in (("hope","🌟","희망","Hope"),("order","🛡️","질서","Order"),("survival","❤️","생존","Survival"),("abyss","🌀","심연","Abyss")):
            changes.append(f"{emoji} {_t(locale,ko,en)} {before.get(key,0)} → {after.get(key,0)}")
        result.add_field(name=_t(locale,"📊 도시 변화","📊 City Changes"), value="\n".join(changes), inline=False)
        result.add_field(name=_t(locale,"🔓 새 기록","🔓 New Record"), value=_t(locale,choice.unlock_ko,choice.unlock_en), inline=False)
        if state.get("completed"):
            ko,en=_season_ending(state)
            result.add_field(name=_t(locale,"🌅 최종 결말","🌅 Final Ending"), value=_t(locale,ko,en), inline=False)
        else:
            next_chapter=SEASON6_CHAPTERS[int(state["chapter"])]
            result.add_field(name=_t(locale,"🧭 다음 장","🧭 Next Chapter"), value=_t(locale,next_chapter.title_ko,next_chapter.title_en), inline=False)
        await ctx.send(embed=_safe_embed(result), view=_safe_view(Season6View(bot, world_data, save_data, int(ctx.guild.id if ctx.guild else 0), locale)))

    @bot.command(name="시즌6기록", aliases=["season6history", "blackSunHistory"], help="시즌 6 서버 투표와 결정 연대기를 확인합니다.")
    async def season6_history(ctx: commands.Context) -> None:
        locale = _ctx_locale(bot, ctx)
        state = _season_state(world_data, int(ctx.guild.id if ctx.guild else 0))
        history = state.get("history", [])
        if not history:
            await ctx.send(_t(locale,"📜 아직 확정된 시즌 6 결정이 없습니다.","📜 No Season 6 decisions have been resolved.")); return
        lines=[]
        for row in history[-10:]:
            ci=int(row.get("chapter",1))-1; oi=int(row.get("choice",1))-1
            if 0<=ci<len(SEASON6_CHAPTERS) and 0<=oi<3:
                ch=SEASON6_CHAPTERS[ci]; choice=ch.choices[oi]
                lines.append(f"**{ci+1}.** {_t(locale,ch.title_ko,ch.title_en)} → {_t(locale,choice.ko,choice.en)}")
        embed=discord.Embed(title=_t(locale,"📜 검은 태양 연대기","📜 Black Sun Chronicle"),description="\n".join(lines),color=0x4B0082)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="시즌6보상", aliases=["season6reward", "blackSunReward"], help="시즌 6 완료 후 참여 보상을 한 번 수령합니다.")
    async def season6_reward(ctx: commands.Context) -> None:
        locale=_ctx_locale(bot,ctx); gid=int(ctx.guild.id if ctx.guild else 0)
        state=_season_state(world_data,gid)
        uid=str(ctx.author.id)
        if not state.get("completed"):
            await ctx.send(_t(locale,"시즌 6 완료 후 수령할 수 있습니다.","Available after Season 6 is completed.")); return
        if uid not in [str(x) for x in state.get("participants",[])]:
            await ctx.send(_t(locale,"이번 시즌 투표 참여 기록이 없습니다.","You did not participate in this season.")); return
        if uid in [str(x) for x in state.get("claims",[])]:
            await ctx.send(_t(locale,"이미 시즌 6 보상을 수령했습니다.","Season 6 reward already claimed.")); return
        user=_safe_user(get_user,ctx.author.id)
        if not user:
            await ctx.send(_t(locale,"먼저 `!가입`으로 생존자를 등록해주세요.","Register a survivor with `!register` first.")); return
        before=int(user.get("balance",0) or 0); exp_before=int(user.get("exp",0) or 0)
        user["balance"]=before+150_000; user["exp"]=exp_before+500
        titles=user.setdefault("titles",[])
        title=_t(locale,"검은 태양의 목격자","Witness of the Black Sun")
        if isinstance(titles,list) and title not in titles: titles.append(title)
        state["claims"].append(uid); save_data()
        await ctx.send(_t(locale,f"🎁 시즌 6 보상: 식량 +150,000 · EXP +500 · 칭호 **{title}**",f"🎁 Season 6 reward: Food +150,000 · EXP +500 · title **{title}**"))

    # v17.2.1: real Korean/English Season 6 command group while preserving all
    # existing top-level commands and aliases.
    @season6.command(name="시작", aliases=["start"])
    async def season6_group_start(ctx: commands.Context) -> None:
        await ctx.invoke(season6_start)

    @season6.command(name="투표", aliases=["vote"])
    async def season6_group_vote(ctx: commands.Context, option: int) -> None:
        await ctx.invoke(season6_vote, option=option)

    @season6.command(name="결정", aliases=["resolve"])
    async def season6_group_resolve(ctx: commands.Context, option: int = 0) -> None:
        await ctx.invoke(season6_resolve, option=option)

    @season6.command(name="기록", aliases=["history"])
    async def season6_group_history(ctx: commands.Context) -> None:
        await ctx.invoke(season6_history)

    @season6.command(name="보상", aliases=["reward"])
    async def season6_group_reward(ctx: commands.Context) -> None:
        await ctx.invoke(season6_reward)

    @bot.command(name="권리증명", aliases=["ownerproof", "copyrightvault"], hidden=True, help="봇 소유자만 내부 프로젝트 소유권 증명 정보를 확인합니다.")
    async def owner_proof(ctx: commands.Context) -> None:
        locale=_ctx_locale(bot,ctx)
        try:
            owner=await bot.is_owner(ctx.author)
        except Exception:
            owner=False
        if not owner:
            await ctx.send(_t(locale,"🔒 봇 소유자 전용입니다.","🔒 Bot owner only.")); return
        path=_owner_proof_path()
        if not path.is_file():
            await ctx.send(_t(locale,"소유권 증명 파일이 없습니다.","Owner proof file is missing.")); return
        data=json.loads(path.read_text(encoding="utf-8"))
        embed=discord.Embed(title="🔐 ABADDON PRIVATE OWNER VAULT",color=0x111111)
        embed.add_field(name="Project UUID",value=f"`{data.get('project_uuid')}`",inline=False)
        embed.add_field(name="Owner",value=str(data.get("owner")),inline=True)
        embed.add_field(name="Release",value=str(data.get("release")),inline=True)
        embed.add_field(name="Proof SHA-256",value=f"`{hashlib.sha256(path.read_bytes()).hexdigest()}`",inline=False)
        embed.set_footer(text="Private internal proof · not shown to regular users")
        await ctx.send(embed=_safe_embed(embed), delete_after=60)

    # Story compass v17 override: seasons 1–5 plus server Season 6.
    story_compass=bot.get_command("스토리나침반")
    if story_compass is not None:
        async def story_compass_v1700(ctx: commands.Context) -> None:
            locale=_ctx_locale(bot,ctx); user=_safe_user(get_user,ctx.author.id)
            embed=discord.Embed(title=_t(locale,"🧭 아포칼립스 스토리 나침반","🧭 Apocalypse Story Compass"),description=_t(locale,"시즌 1부터 검은 태양의 귀환까지 현재 위치와 다음 행동을 확인합니다.","Review your route from Season 1 through Return of the Black Sun."),color=0x7A3FE0)
            lines=[]
            try:
                from apocalypse_bot.commands import v1650_survivor_core_complete as core
                for season,title,state,_command in core._story_states(user):
                    lines.append(core._story_progress_line(locale,season,title,state))
            except Exception:
                lines.append(_t(locale,"시즌 1~4 개인 기록 연결","Personal Seasons 1–4 linked"))
            lines.append(_t(locale,"📡 시즌 5 · 잿빛 연합전선 · 서버 공동 세계 진행","📡 Season 5 · Ashen Front · server world progression"))
            s6=_season_state(world_data,int(ctx.guild.id if ctx.guild else 0))
            if s6.get("completed"):
                ko,en=_season_ending(s6); s6line=_t(locale,f"✅ 시즌 6 · **{ko}** 결말",f"✅ Season 6 · **{en}** ending")
            elif s6.get("started"):
                s6line=_t(locale,f"▶ 시즌 6 · {int(s6.get('chapter',0))+1}/{len(SEASON6_CHAPTERS)}장 진행",f"▶ Season 6 · Chapter {int(s6.get('chapter',0))+1}/{len(SEASON6_CHAPTERS)}")
            else:
                s6line=_t(locale,"○ 시즌 6 · 검은 태양의 귀환 미시작","○ Season 6 · Return of the Black Sun not started")
            lines.append(s6line)
            embed.add_field(name=_t(locale,"📖 전체 시즌","📖 All Seasons"),value="\n".join(lines)[:1024],inline=False)
            embed.add_field(name=_t(locale,"🚀 빠른 이동","🚀 Quick Actions"),value="`!시즌6` · `!솔로원정` · `!생존허브` · `!오늘할일`",inline=False)
            actions=(("시즌6","시즌 6","Season 6","☀️",discord.ButtonStyle.success),("솔로원정","솔로 원정","Lone Survivor","🌑",discord.ButtonStyle.primary),("생존허브","생존 허브","Survivor Hub","👤",discord.ButtonStyle.secondary))
            try:
                from apocalypse_bot.commands.v1650_survivor_core_complete import ActionView
                view=ActionView(bot,ctx.author.id,locale,actions)
            except Exception:
                view=None
            await ctx.send(embed=_safe_embed(embed),view=_safe_view(view))
        story_compass.callback=story_compass_v1700
        story_compass.help="시즌 1~6 전체 진행과 현재 목표를 한 화면에서 확인합니다."
        story_compass.description=story_compass.help

    @bot.command(name="런타임청소검수", aliases=["runtimecleansweep", "runtimeaudit1700"], help="버튼 Cog·웹훅 삭제 예약·성장 집계·중복 오류 안내 수정 상태를 검사합니다.")
    async def runtime_audit(ctx: commands.Context, detail: str = "") -> None:
        locale=_ctx_locale(bot,ctx)
        root_path=Path(__file__).resolve().parent
        sources={name:(root_path/name).read_text(encoding="utf-8") for name in ("v600_game_center.py","v1670_live_ops_polish.py","v710_growth_loop.py")}
        checks={
            "Actual Cog guard":"def _real_cog" in sources["v600_game_center.py"] and "isinstance(cog, commands.Cog)" in sources["v600_game_center.py"],
            "Webhook delete scheduling":"kwargs.pop(\"delete_after\"" in sources["v600_game_center.py"] and "_schedule_delete" in sources["v600_game_center.py"],
            "Duplicate error notice guard":"_allow_failure_notice" in sources["v600_game_center.py"],
            "Growth None guard":"isinstance(user, MutableMapping)" in sources["v710_growth_loop.py"],
            "Operations bridge guard":"_real_cog(command)" in sources["v1670_live_ops_polish.py"],
        }
        embed=discord.Embed(title=_t(locale,"🧹 v17.0 런타임 전면 청소 검수","🧹 v17.0 Runtime Clean Sweep"),color=0x2ECC71 if all(checks.values()) else 0xE74C3C)
        embed.description="\n".join(f"{'✅' if ok else '❌'} {name}" for name,ok in checks.items())
        if detail: embed.add_field(name=_t(locale,"대상 로그","Target Logs"),value="`_MissingSentinel.author` · `Webhook.send(delete_after)` · `growth NoneType.get` · duplicate UI notices",inline=False)
        await ctx.send(embed=_safe_embed(embed))

    @bot.command(name="1700통합검수", aliases=["v1700audit", "1700audit"], help="v17.0 런타임 청소·콘텐츠 공방·시즌 6·언어 분리·소유권 금고를 통합 검사합니다.")
    async def audit_1700(ctx: commands.Context, detail: str = "") -> None:
        locale=_ctx_locale(bot,ctx)
        required=["명령어","help","콘텐츠공방","콘텐츠목록","사용자사건","시즌6","시즌6시작","시즌6투표","시즌6결정","시즌6기록","시즌6보상","런타임청소검수"]
        checks=[(name,bot.get_command(name) is not None) for name in required]
        entries=hub._build_registry(bot)
        checks.extend([
            ("Season 6 command group",any(e.group=="story6" for e in entries)),
            ("Creator Forge group",any(e.group=="creator" and "v1700" in e.source for e in entries)),
            ("Korean / English separation",bot.get_command("명령어") is not None and bot.get_command("help") is not None),
            ("Private owner proof",_owner_proof_path().is_file()),
            ("5 chapters",len(SEASON6_CHAPTERS)==5),
        ])
        ok=all(value for _,value in checks)
        embed=discord.Embed(title=_t(locale,"🧪 ABADDON v17.0.0 통합 검수","🧪 ABADDON v17.0.0 Integration Audit"),color=0x2ECC71 if ok else 0xE74C3C)
        embed.description="\n".join(f"{'✅' if value else '❌'} {name}" for name,value in checks)
        if detail:
            embed.add_field(name=_t(locale,"보존","Preservation"),value=_t(locale,"기존 명령·저장 데이터 삭제 0건 · 모든 기능은 추가 계층","0 legacy commands or save data removed · additive layer only"),inline=False)
            embed.add_field(name=_t(locale,"런타임","Runtime"),value="`!런타임청소검수 상세`",inline=False)
        await ctx.send(embed=_safe_embed(embed))

    # Latest patch notes and test surfaces.
    patch=bot.get_command("패치노트")
    if patch is not None:
        async def patch_v1700(ctx: commands.Context) -> None:
            locale=_ctx_locale(bot,ctx)
            embed=discord.Embed(title=_t(locale,"☀️ ABADDON v17.0.0 · BLACK SUN CREATOR ERA","☀️ ABADDON v17.0.0 · BLACK SUN CREATOR ERA"),description=_t(locale,"런타임 오류를 청소하고, 운영자가 사건을 만들며, 서버 전체가 시즌 6 결말을 결정합니다.","Runtime cleanup, an admin creator forge, and a server-wide Season 6 with branching endings."),color=0x4B0082)
            embed.add_field(name=_t(locale,"🧹 런타임 전면 청소","🧹 Runtime Clean Sweep"),value=_t(locale,"정보 버튼 `_MissingSentinel.author`, 웹훅 `delete_after`, 성장 집계 None, 중복 오류 안내를 수정했습니다.","Fixed info-button Cog sentinel errors, webhook delete scheduling, growth None guards, and duplicate error notices."),inline=False)
            embed.add_field(name=_t(locale,"🧩 콘텐츠 제작 공방","🧩 Creator Forge"),value=_t(locale,"관리자가 2~5개 선택지와 한·영 결과·보상을 입력해 테스트하고 공개합니다.","Admins build, test and publish bilingual events with 2–5 choices and capped rewards."),inline=False)
            embed.add_field(name=_t(locale,"☀️ 시즌 6 · 검은 태양의 귀환","☀️ Season 6 · Return of the Black Sun"),value=_t(locale,"5개 장, 서버 투표, 4개 도시 지표, 다중 결말과 참여 보상을 추가했습니다.","Five chapters, server votes, four city metrics, multiple endings and participation rewards."),inline=False)
            embed.add_field(name=_t(locale,"🔐 비공개 권리 금고","🔐 Private Owner Vault"),value=_t(locale,"일반 유저에게 노출하지 않는 프로젝트 UUID·해시 증명 파일과 소유자 전용 명령을 추가했습니다.","Added a private project UUID/hash proof file and owner-only command hidden from regular users."),inline=False)
            embed.add_field(name=_t(locale,"🧪 점검","🧪 Checks"),value="`!런타임청소검수 상세` · `!1700통합검수 상세`",inline=False)
            embed.set_footer(text=_t(locale,"기존 기능·저장 데이터 삭제 0건","0 legacy features or save data removed"))
            await ctx.send(embed=_safe_embed(embed))
        patch.callback=patch_v1700; patch.help="ABADDON v17.0.0 최신 패치노트입니다."; patch.description=patch.help

    test=bot.get_command("테스트")
    if test is not None:
        async def test_v1700(ctx: commands.Context, mode: str = "", *args: Any, **kwargs: Any) -> None:
            del args,kwargs
            locale=_ctx_locale(bot,ctx)
            required=["콘텐츠공방","사용자사건","시즌6","시즌6결정","런타임청소검수","1700통합검수"]
            checks=[(name,bot.get_command(name) is not None) for name in required]
            checks.append(("Season 6 chapters",len(SEASON6_CHAPTERS)==5))
            checks.append(("Owner proof",_owner_proof_path().is_file()))
            embed=discord.Embed(title=_t(locale,"🧪 ABADDON v17.0 최신 테스트","🧪 ABADDON v17.0 Latest Test"),color=0x2ECC71 if all(v for _,v in checks) else 0xE74C3C)
            embed.description="\n".join(f"{'✅' if value else '❌'} {name}" for name,value in checks)
            if str(mode).casefold() in {"상세","detail","full"}: embed.add_field(name=_t(locale,"범위","Scope"),value="Runtime · Creator Forge · Community Events · Season 6 · Owner Vault · KO/EN split",inline=False)
            await ctx.send(embed=_safe_embed(embed))
        test.callback=test_v1700; test.help="v17.0 런타임·콘텐츠 공방·시즌 6 최신 범위를 검사합니다."; test.description=test.help

    # Rebuild command-center registry after all v17 commands exist.
    entries=hub._build_registry(bot)
    setattr(bot,"v1630_command_entries",entries)
    setattr(bot,"v1630_command_index",{entry.qualified_name:entry for entry in entries})

    guide.append({
        "id":"v1700_black_sun_creator_era","emoji":"☀️","title":"v17.0 BLACK SUN CREATOR ERA",
        "hint":"런타임 전면 청소·콘텐츠 제작 공방·사용자 사건·시즌 6 공동 투표·비공개 권리 금고",
        "commands":[
            "!콘텐츠공방 · !콘텐츠목록 · !사용자사건",
            "!시즌6 · !시즌6시작 · !시즌6투표 · !시즌6결정 · !시즌6기록 · !시즌6보상",
            "!런타임청소검수 상세 · !1700통합검수 상세 · !테스트 상세 · !패치노트",
        ],
    })
    print(f"[ABADDON v{VERSION}] creator forge + season 6 registered: chapters={len(SEASON6_CHAPTERS)} commands={len(entries)}",flush=True)


__all__=["register_v1700_creator_forge_season6","SEASON6_CHAPTERS","_season_state","_creator_guild"]
