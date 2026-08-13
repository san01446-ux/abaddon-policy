from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

VERSION = "6.5.3"
ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets" / "v631"
KST = ZoneInfo("Asia/Seoul")
ENCOUNTER_CHANCE = 0.10
ENCOUNTER_DAILY_LIMIT = 12
ENCOUNTER_REWARD_CAP = 40_000
VALUABLE_ITEM_CHANCE = 0.03
VALUABLE_ITEM_DAILY_LIMIT = 1

ACTIVITY_LABELS: Mapping[str, Tuple[str, str]] = {
    "work": ("🧰", "폐허 알바"),
    "digging": ("⛏️", "땅파기"),
    "gathering": ("🌿", "채집"),
    "woodcutting": ("🪓", "벌목"),
}

ACTIVITY_ALIASES = {"알바": "work", "땅파기": "digging", "채집": "gathering", "벌목": "woodcutting"}

TIP_POOLS: Mapping[str, Sequence[str]] = {
    "work": (
        "알바 레벨이 오를수록 사고 확률은 낮아지고 대성공 확률은 조금씩 높아집니다.",
        "작업 중 얻은 고철·광석·나무는 제작과 기지 강화에 사용할 수 있습니다.",
        "코인 탐색을 모두 사용했다면 알바, 알바까지 끝냈다면 땅파기가 다음 수입 루트입니다.",
        "위험한 선택지는 보상이 높지만 수리비나 체력 손실이 생길 수 있습니다.",
    ),
    "digging": (
        "미감정 보물은 `!보물감정`에서 감정사를 골라 확인할 수 있습니다.",
        "땅파기는 일반 물자를 찾지 못해도 소량의 굴착 잔돈을 확보합니다.",
        "붕괴 신호가 보이면 빠른 회수보다 통로 보강이 안전합니다.",
        "같은 인카운트가 연달아 나오지 않도록 최근 조우 기록을 반영합니다.",
    ),
    "gathering": (
        "채집 숙련도는 20회마다 올라가며 평균 획득량을 높여 줍니다.",
        "빛나는 식물은 가치가 높지만 주변 변이 생물을 자극할 수 있습니다.",
        "약초는 제작과 회복 계열 콘텐츠에 활용됩니다.",
        "오염이 짙은 구역에서는 무리한 채집보다 표본만 확보하는 편이 안전합니다.",
    ),
    "woodcutting": (
        "나무는 기지 건설과 성장에 가장 많이 사용되는 생활 자원입니다.",
        "오염된 괴목은 수확량이 많지만 장비 파손 위험도 높습니다.",
        "벌목 숙련도가 오르면 한 번에 얻는 나무의 양이 늘어납니다.",
        "큰 소음은 약탈자나 변이 생물을 끌어들일 수 있습니다.",
    ),
}

_RECENT_ASSETS: Dict[str, List[str]] = {}
FIXED_ASSET_MAP: Mapping[str, str] = {
    "activities/work/encounter": "activities/work/encounter/02.jpg",
    "activities/work/encounter_success": "activities/work/success/03.jpg",
    "activities/work/encounter_failure": "activities/work/failure/01.jpg",
    "activities/work/success": "activities/work/success/01.jpg",
    "activities/work/failure": "activities/work/failure/01.jpg",
    "activities/work/rare": "activities/work/success/02.jpg",
    "activities/digging/encounter": "activities/digging/encounter/01.jpg",
    "activities/digging/encounter_success": "activities/digging/encounter_success/01.jpg",
    "activities/digging/encounter_failure": "activities/digging/failure/01.jpg",
    "activities/digging/success": "activities/digging/success/01.jpg",
    "activities/digging/failure": "activities/digging/failure/01.jpg",
    "activities/digging/rare": "activities/digging/rare/01.jpg",
    "activities/gathering/encounter": "activities/gathering/success/01.jpg",
    "activities/gathering/encounter_success": "activities/gathering/success/02.jpg",
    "activities/gathering/encounter_failure": "activities/gathering/failure/01.jpg",
    "activities/gathering/success": "activities/gathering/success/03.jpg",
    "activities/gathering/failure": "activities/gathering/failure/02.jpg",
    "activities/gathering/rare": "activities/gathering/rare/01.jpg",
    "activities/woodcutting/encounter": "activities/woodcutting/rare/02.jpg",
    "activities/woodcutting/encounter_success": "activities/woodcutting/success/03.jpg",
    "activities/woodcutting/encounter_failure": "activities/woodcutting/rare/01.jpg",
    "activities/woodcutting/success": "activities/woodcutting/success/01.jpg",
    "activities/woodcutting/failure": "activities/woodcutting/success/02.jpg",
    "activities/woodcutting/rare": "activities/woodcutting/rare/01.jpg",
}
_ACTIVE_USERS: set[int] = set()
_ITEM_DB: Mapping[str, Mapping[str, Mapping[str, Any]]] = {}

CATEGORY_GALLERY_POOLS: Mapping[str, str] = {
    "activities/gathering/": "activities/gathering/gallery",
}



def random_tip(activity: str) -> str:
    pool = TIP_POOLS.get(activity) or ("현장 상황에 따라 안전한 선택이 더 좋은 결과가 될 수 있습니다.",)
    return random.choice(tuple(pool))


def _asset_files(relative: str) -> List[Path]:
    folder = ASSET_ROOT / relative
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})


def pick_asset(relative: str) -> Optional[Path]:
    recent_key = relative
    for prefix, gallery in CATEGORY_GALLERY_POOLS.items():
        if relative.startswith(prefix):
            files = _asset_files(gallery)
            recent_key = gallery
            break
    else:
        fixed = FIXED_ASSET_MAP.get(relative)
        if fixed:
            path = ASSET_ROOT / fixed
            if path.is_file():
                return path
        files = _asset_files(relative)
    if not files:
        return None
    recent = _RECENT_ASSETS.setdefault(recent_key, [])
    blocked = set(recent[-3:])
    choices = [p for p in files if p.name not in blocked] or files
    selected = random.choice(choices)
    recent.append(selected.name)
    del recent[:-6]
    return selected


def _discord_file(path: Path) -> discord.File:
    safe = "_".join(path.relative_to(ASSET_ROOT).parts)
    return discord.File(str(path), filename=f"abaddon_{safe}")


def _set_image(embed: discord.Embed, path: Optional[Path]) -> Optional[discord.File]:
    if path is None or not path.is_file():
        return None
    file = _discord_file(path)
    embed.set_image(url=f"attachment://{file.filename}")
    return file


async def _add_reactions(message: Any, emojis: Sequence[str]) -> None:
    for emoji in emojis[:3]:
        try:
            await message.add_reaction(emoji)
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            break


async def send_visual(target: Any, embed: discord.Embed, relative: str, *, view: Optional[discord.ui.View] = None) -> discord.Message:
    file = _set_image(embed, pick_asset(relative))
    kwargs: Dict[str, Any] = {"embed": embed}
    if view is not None:
        kwargs["view"] = view
    if file is not None:
        kwargs["file"] = file
    return await target.send(**kwargs)


async def edit_visual(message: discord.Message, embed: discord.Embed, relative: str, *, view: Optional[discord.ui.View] = None) -> None:
    file = _set_image(embed, pick_asset(relative))
    try:
        if file is not None:
            await message.edit(content=None, embed=embed, view=view, attachments=[file])
        else:
            await message.edit(content=None, embed=embed, view=view)
    except TypeError:
        await message.edit(content=None, embed=embed, view=view)
    except (discord.Forbidden, discord.HTTPException, AttributeError):
        return


@dataclass(frozen=True)
class Encounter:
    encounter_id: str
    activity: str
    rarity: str
    title: str
    description: str
    options: Tuple[Tuple[str, str, str], ...]


ENCOUNTERS: Tuple[Encounter, ...] = (
    Encounter("work_power_fault", "work", "danger", "폐허 발전기 역전류", "배전반에서 붉은 스파크가 튀며 작업장 전체 전력이 흔들립니다.", (("차단기를 내린다", "🔌", "safe"), ("고장 부품을 교체한다", "🛠️", "help"), ("전력을 유지한 채 강행한다", "⚡", "risk"))),
    Encounter("work_raider_route", "work", "danger", "약탈자 운송로", "보급품을 옮기던 중 약탈자 정찰 흔적과 우회 통로를 발견했습니다.", (("조용히 우회한다", "🥾", "safe"), ("거점에 경고를 보낸다", "📻", "help"), ("버려진 화물을 회수한다", "📦", "risk"))),
    Encounter("work_hidden_store", "work", "rare", "봉인된 비상 창고", "무너진 작업대 뒤에서 오래된 비상 창고의 잠금 장치를 찾았습니다.", (("잠금 장치를 해제한다", "🔐", "safe"), ("기술자를 불러 함께 연다", "🧰", "help"), ("문을 강제로 뜯는다", "🔨", "risk"))),
    Encounter("digging_collapse", "digging", "danger", "무너지는 지하 통로", "굴착면 너머에서 토사가 쏟아지고 금속 상자 모서리가 드러났습니다.", (("통로를 보강한다", "🧱", "safe"), ("동료와 잔해를 치운다", "🤝", "help"), ("상자만 빠르게 끌어낸다", "⛏️", "risk"))),
    Encounter("digging_old_relic", "digging", "rare", "고대 장치의 맥동", "진흙 속 원형 장치에서 희미한 푸른빛과 규칙적인 진동이 감지됩니다.", (("표면만 조사한다", "🔍", "safe"), ("기록을 남기며 분리한다", "📜", "help"), ("즉시 작동시킨다", "💠", "risk"))),
    Encounter("digging_survivor_cache", "digging", "common", "생존자의 은닉 상자", "낡은 표식 아래에서 식량과 공구가 든 작은 은닉처를 발견했습니다.", (("필요한 것만 챙긴다", "🎒", "safe"), ("일부를 거점에 기부한다", "🫱", "help"), ("깊숙한 이중 바닥을 연다", "🗝️", "risk"))),
    Encounter("gathering_spore_field", "gathering", "danger", "형광 포자 군락", "빛나는 버섯 주변에 미세한 포자가 안개처럼 퍼지고 있습니다.", (("외곽 표본만 채취한다", "🧪", "safe"), ("방독 장비를 나눠 쓴다", "😷", "help"), ("군락 중심으로 들어간다", "🍄", "risk"))),
    Encounter("gathering_trader", "gathering", "common", "떠돌이 약초상", "임시 천막 아래에서 희귀 약초를 분류하는 떠돌이 상인을 만났습니다.", (("소량 교환한다", "🤝", "safe"), ("채집 정보를 공유한다", "🗺️", "help"), ("봉인된 표본을 산다", "🧫", "risk"))),
    Encounter("gathering_seed_vault", "gathering", "rare", "보존 종자 보관함", "폐온실 바닥 아래에서 아직 전력이 남은 종자 보관함을 발견했습니다.", (("외부 상태를 확인한다", "🔎", "safe"), ("냉각 장치를 복구한다", "🔧", "help"), ("비상 해제를 누른다", "🚨", "risk"))),
    Encounter("woodcutting_mutant_sap", "woodcutting", "danger", "변이 수액이 흐르는 괴목", "도끼 자국에서 녹색 수액이 솟으며 주변 뿌리가 움직이기 시작합니다.", (("수액을 피해 절단한다", "🪓", "safe"), ("표본을 채취한다", "🧪", "help"), ("심부를 한 번에 벤다", "💥", "risk"))),
    Encounter("woodcutting_watchtower", "woodcutting", "common", "폐쇄된 산림 감시소", "쓰러진 나무 뒤로 오래된 감시소와 잠긴 공구함이 보입니다.", (("주변을 먼저 살핀다", "👁️", "safe"), ("감시 기록을 복구한다", "📡", "help"), ("공구함을 강제로 연다", "🔧", "risk"))),
    Encounter("woodcutting_trap", "woodcutting", "rare", "약탈자의 와이어 덫", "벌목로에 숨겨진 와이어 덫과 그 너머의 보급 자루를 발견했습니다.", (("덫을 표시하고 우회한다", "🚩", "safe"), ("덫을 해체한다", "✂️", "help"), ("보급 자루부터 낚아챈다", "🎯", "risk"))),
)


def _kst_date() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _ensure_profile(user: Dict[str, Any]) -> Dict[str, Any]:
    profile = user.setdefault("life_encounters_v631", {})
    defaults = {"date": _kst_date(), "daily_count": 0, "daily_reward": 0, "daily_item_drops": 0, "total": 0, "seen": [], "recent": [], "choices": {}, "last_at": ""}
    for key, value in defaults.items():
        profile.setdefault(key, value.copy() if isinstance(value, (dict, list)) else value)
    if profile.get("date") != _kst_date():
        profile["date"] = _kst_date()
        profile["daily_count"] = 0
        profile["daily_reward"] = 0
        profile["daily_item_drops"] = 0
    return profile



def _try_valuable_item(user: Dict[str, Any], profile: Dict[str, Any]) -> str:
    """Very rare, once-per-day tradeable equipment reward from existing ITEM_DB."""
    if not _ITEM_DB or int(profile.get("daily_item_drops", 0)) >= VALUABLE_ITEM_DAILY_LIMIT:
        return ""
    if random.random() >= VALUABLE_ITEM_CHANCE:
        return ""
    inventory = set(user.get("inventory", []))
    equipped = {x for x in user.get("equipment", {}).values() if x}
    tier = random.choices(("영웅", "전설"), weights=(76, 24), k=1)[0]
    candidates = [
        (name, info) for name, info in _ITEM_DB.get(tier, {}).items()
        if name not in inventory and name not in equipped
    ]
    if not candidates:
        other = "전설" if tier == "영웅" else "영웅"
        tier = other
        candidates = [
            (name, info) for name, info in _ITEM_DB.get(tier, {}).items()
            if name not in inventory and name not in equipped
        ]
    if not candidates:
        return ""
    name, info = random.choice(candidates)
    user.setdefault("inventory", []).append(name)
    user.setdefault("enhancements", {}).setdefault(name, 0)
    profile["daily_item_drops"] = int(profile.get("daily_item_drops", 0)) + 1
    price = int(info.get("price", 0))
    return f" · 🎁 [{tier}] **{name}** 획득 (기준가 {price:,} 식량 · `!판매 {name} 가격`)"

def _resource_for(activity: str) -> str:
    return {"work": "고철", "digging": "고철", "gathering": "약초", "woodcutting": "나무"}[activity]


def _apply_outcome(user: Dict[str, Any], profile: Dict[str, Any], encounter: Encounter, mode: str) -> Tuple[str, int]:
    base_chance = {"safe": 0.82, "help": 0.72, "risk": 0.54}.get(mode, 0.65)
    if encounter.rarity == "rare":
        base_chance -= 0.05
    elif encounter.rarity == "danger":
        base_chance -= 0.08
    success = random.random() < max(0.25, min(0.93, base_chance))
    if success:
        room = max(0, ENCOUNTER_REWARD_CAP - int(profile.get("daily_reward", 0)))
        reward = min(room, random.randint(180, 650 if mode == "safe" else 1000 if mode == "help" else 1700))
        resource = _resource_for(encounter.activity)
        amount = random.randint(1, 3 if mode == "safe" else 5 if mode == "help" else 8)
        user["balance"] = int(user.get("balance", 0)) + reward
        user.setdefault("stats", {}).setdefault("earned", 0)
        user["stats"]["earned"] = int(user["stats"].get("earned", 0)) + reward
        user.setdefault("resources", {})
        user["resources"][resource] = int(user["resources"].get(resource, 0)) + amount
        rare = ""
        if encounter.rarity == "rare" and random.random() < 0.24:
            user.setdefault("materials", {})
            user["materials"]["고대파편"] = int(user["materials"].get("고대파편", 0)) + 1
            rare = " · 🧩 고대파편 +1"
        valuable = _try_valuable_item(user, profile)
        profile["daily_reward"] = int(profile.get("daily_reward", 0)) + reward
        return f"선택이 성공했습니다. 💰 식량 +{reward:,} · 📦 {resource} +{amount}{rare}{valuable}", reward
    balance = max(0, int(user.get("balance", 0)))
    loss_max = 280 if mode == "safe" else 550 if mode == "help" else 1000
    loss = min(balance, random.randint(50, loss_max))
    user["balance"] = balance - loss
    hp_loss = random.randint(0, 3 if mode == "safe" else 6 if mode == "help" else 10)
    if hp_loss and isinstance(user.get("hp"), int):
        user["hp"] = max(1, int(user["hp"]) - hp_loss)
    hp_text = f" · ❤️ HP -{hp_loss}" if hp_loss else ""
    return f"현장 변수를 피하지 못해 철수했습니다. 💸 식량 -{loss:,}{hp_text}", -loss


class EncounterView(discord.ui.View):
    def __init__(self, *, owner_id: int, encounter: Encounter, user: Dict[str, Any], save_data: Callable[[], None]) -> None:
        super().__init__(timeout=150)
        self.owner_id = int(owner_id)
        self.encounter = encounter
        self.user = user
        self.save_data = save_data
        self.resolved = False
        self.message: Optional[discord.Message] = None
        for label, emoji, mode in encounter.options:
            style = discord.ButtonStyle.danger if mode == "risk" else discord.ButtonStyle.success if mode == "help" else discord.ButtonStyle.primary
            button = discord.ui.Button(label=label, emoji=emoji, style=style)
            async def callback(interaction: discord.Interaction, *, selected_mode: str = mode, selected_label: str = label) -> None:
                await self._resolve(interaction, selected_mode, selected_label)
            button.callback = callback
            self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) != self.owner_id:
            await interaction.response.send_message("이 인카운트는 발견한 생존자만 선택할 수 있습니다.", ephemeral=True)
            return False
        return True

    async def _resolve(self, interaction: discord.Interaction, mode: str, label: str) -> None:
        if self.resolved:
            await interaction.response.send_message("이미 선택이 끝난 인카운트입니다.", ephemeral=True)
            return
        self.resolved = True
        profile = _ensure_profile(self.user)
        text, delta = _apply_outcome(self.user, profile, self.encounter, mode)
        profile["choices"][self.encounter.encounter_id] = int(profile["choices"].get(self.encounter.encounter_id, 0)) + 1
        profile["last_at"] = datetime.now(timezone.utc).isoformat()
        self.save_data()
        for item in self.children:
            item.disabled = True
        emoji, label_text = ACTIVITY_LABELS[self.encounter.activity]
        embed = discord.Embed(
            title=f"{emoji} 인카운트 결과 · {self.encounter.title}",
            description=f"선택: **{label}**\n\n{text}",
            color=discord.Color.green() if delta > 0 else discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="💳 현재 잔액", value=f"**{int(self.user.get('balance', 0)):,} 식량**", inline=True)
        embed.add_field(name="📚 도감", value=f"`!인카운트도감` · {label_text}", inline=True)
        embed.add_field(name="💡 TIP", value=random_tip(self.encounter.activity), inline=False)
        relative = f"activities/{self.encounter.activity}/encounter_success" if delta > 0 else f"activities/{self.encounter.activity}/encounter_failure"
        path = pick_asset(relative)
        file = _set_image(embed, path)
        kwargs: Dict[str, Any] = {"embed": embed, "view": self}
        if file is not None:
            kwargs["attachments"] = [file]
        try:
            await interaction.response.edit_message(**kwargs)
        except (discord.HTTPException, TypeError):
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=self)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
        if self.message is not None:
            await _add_reactions(self.message, ("✅", "✨") if delta > 0 else ("⚠️", "🛠️"))
        _ACTIVE_USERS.discard(self.owner_id)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        _ACTIVE_USERS.discard(self.owner_id)
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except (discord.Forbidden, discord.HTTPException, AttributeError):
                pass


async def maybe_encounter(ctx: commands.Context, activity: str, user: Dict[str, Any], save_data: Callable[[], None]) -> Optional[discord.Message]:
    activity = ACTIVITY_ALIASES.get(activity, activity)
    if activity not in ACTIVITY_LABELS or int(ctx.author.id) in _ACTIVE_USERS:
        return None
    profile = _ensure_profile(user)
    if int(profile.get("daily_count", 0)) >= ENCOUNTER_DAILY_LIMIT or random.random() >= ENCOUNTER_CHANCE:
        return None
    candidates = [e for e in ENCOUNTERS if e.activity == activity]
    recent = list(profile.get("recent", []))[-2:]
    candidates = [e for e in candidates if e.encounter_id not in recent] or candidates
    weights = [5 if e.rarity == "common" else 3 if e.rarity == "danger" else 2 for e in candidates]
    encounter = random.choices(candidates, weights=weights, k=1)[0]
    profile["daily_count"] = int(profile.get("daily_count", 0)) + 1
    profile["total"] = int(profile.get("total", 0)) + 1
    if encounter.encounter_id not in profile["seen"]:
        profile["seen"].append(encounter.encounter_id)
    profile["recent"].append(encounter.encounter_id)
    del profile["recent"][:-5]
    save_data()
    _ACTIVE_USERS.add(int(ctx.author.id))

    emoji, activity_label = ACTIVITY_LABELS[activity]
    rarity_label = {"common": "일반", "rare": "희귀", "danger": "위험"}[encounter.rarity]
    embed = discord.Embed(
        title=f"{emoji} 랜덤 인카운트 · {encounter.title}",
        description=f"**{activity_label} 도중 예상치 못한 상황이 발생했습니다.**\n\n{encounter.description}",
        color=discord.Color.gold() if encounter.rarity == "rare" else discord.Color.red() if encounter.rarity == "danger" else discord.Color.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="희귀도", value=f"**{rarity_label}**", inline=True)
    embed.add_field(name="오늘 남은 조우", value=f"**{ENCOUNTER_DAILY_LIMIT - int(profile['daily_count'])}회**", inline=True)
    embed.add_field(name="선택 제한", value="**150초**", inline=True)
    embed.add_field(name="💡 TIP", value=random_tip(activity), inline=False)
    view = EncounterView(owner_id=ctx.author.id, encounter=encounter, user=user, save_data=save_data)
    try:
        message = await send_visual(ctx, embed, f"activities/{activity}/encounter", view=view)
    except Exception:
        _ACTIVE_USERS.discard(int(ctx.author.id))
        raise
    view.message = message
    return message


def register_v631_life_visuals(bot: commands.Bot, get_user: Callable[[int], Dict[str, Any]], check_registered: Callable[..., Any], save_data: Callable[[], None], item_db: Optional[Mapping[str, Mapping[str, Mapping[str, Any]]]] = None) -> None:
    global _ITEM_DB
    _ITEM_DB = item_db or {}
    @bot.command(name="인카운트도감", aliases=["조우도감", "랜덤이벤트도감"])
    async def encounter_codex(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        profile = _ensure_profile(user)
        seen = set(profile.get("seen", []))
        lines = []
        for activity, (emoji, label) in ACTIVITY_LABELS.items():
            entries = [e for e in ENCOUNTERS if e.activity == activity]
            found = [e.title for e in entries if e.encounter_id in seen]
            lines.append(f"{emoji} **{label}** {len(found)}/{len(entries)}\n└ " + (", ".join(found) if found else "아직 발견하지 못함"))
        embed = discord.Embed(title=f"📚 {ctx.author.display_name}의 인카운트 도감", description="\n\n".join(lines), color=discord.Color.dark_teal())
        embed.add_field(name="누적 조우", value=f"**{int(profile.get('total', 0))}회**", inline=True)
        embed.add_field(name="오늘 조우", value=f"**{int(profile.get('daily_count', 0))}/{ENCOUNTER_DAILY_LIMIT}회**", inline=True)
        embed.add_field(name="오늘 조우 수익", value=f"**{int(profile.get('daily_reward', 0)):,}/{ENCOUNTER_REWARD_CAP:,} 식량**", inline=False)
        embed.add_field(name="희귀 거래 장비", value=f"**{int(profile.get('daily_item_drops', 0))}/{VALUABLE_ITEM_DAILY_LIMIT}개**", inline=True)
        await send_visual(ctx, embed, "activities/digging/encounter")

    setattr(bot, "v631_send_visual", send_visual)
    setattr(bot, "v631_edit_visual", edit_visual)
    setattr(bot, "v631_tip", random_tip)
    setattr(bot, "v631_maybe_encounter", lambda ctx, activity, user: maybe_encounter(ctx, activity, user, save_data))
    setattr(bot, "v631_visual_version", VERSION)
