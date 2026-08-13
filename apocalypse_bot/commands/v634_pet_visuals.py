from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

import discord
from discord.ext import commands

VERSION = "6.3.4"
ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets" / "v634" / "pets"

PET_SLUGS: Dict[str, str] = {
    "폐허쥐": "ruin_rat",
    "정찰까마귀": "scout_crow",
    "군견제로": "war_dog_zero",
    "변이살쾡이": "mutant_lynx",
    "미니드론": "mini_drone",
    "어린하이드라": "young_hydra",
    "공허의새끼용": "void_dragon",
    '아바돈': 'abaddon_pet',
    '다크프': 'darkp',
    '루나냥': 'luna_nyang',
    '파이어몽': 'fire_mong',
    '스노우씨': 'snow_ssi',
    '메카로보': 'mecha_robo',
    '썬더드래곤': 'thunder_dragon',
    '포레스트': 'forest_spirit',
    '미니골렘': 'mini_golem',
    '유니콘': 'unicorn',
    '헤르메스': 'hermes',
    '네온문': 'neon_moon',
}

RARITY_COLORS = {
    "일반": 0xB8C7D6,
    "고급": 0x59DC99,
    "희귀": 0x54A8FF,
    "영웅": 0xBF63FF,
    "전설": 0xFFB14A,
    "신화": 0xFF587B,
    "초월": 0x9169FF,
}

MODE_TITLES = {
    "shop": "🐾 펫 동료 상점",
    "buy": "💞 새로운 동료",
    "list": "🐾 현재 동행 펫",
    "equip": "⭐ 동행 펫 변경",
    "info": "📖 펫 정보",
    "train": "🏋️ 펫 훈련 완료",
    "feed": "🍖 간식 시간",
    "adventure": "🧭 펫 모험 귀환",
    "evolve": "✨ 펫 진화 완료",
}


def _clamp_stage(value: Any) -> int:
    try:
        return max(0, min(2, int(value or 0)))
    except (TypeError, ValueError):
        return 0


def pet_asset_path(pet_name: str, stage: int = 0) -> Optional[Path]:
    slug = PET_SLUGS.get(str(pet_name))
    if not slug:
        return None
    path = ASSET_ROOT / slug / f"{_clamp_stage(stage)}.jpg"
    return path if path.is_file() else None


def pet_file(pet_name: str, stage: int = 0, prefix: str = "pet") -> Optional[discord.File]:
    path = pet_asset_path(pet_name, stage)
    if path is None:
        return None
    safe = PET_SLUGS.get(pet_name, "pet")
    return discord.File(str(path), filename=f"abaddon_v634_{prefix}_{safe}_{_clamp_stage(stage)}.jpg")


class PetBrowseSelect(discord.ui.Select):
    def __init__(self, view: "PetBrowseView") -> None:
        self.menu_view = view
        options = []
        owned = view.collection
        for name, info in view.pet_db.items():
            marker = "보유" if name in owned else f"식량 {int(info.get('price', 0)):,}"
            options.append(
                discord.SelectOption(
                    label=name,
                    value=name,
                    emoji=info.get("emoji") or "🐾",
                    description=f"{info.get('rarity', '일반')} · {marker}"[:100],
                )
            )
        super().__init__(placeholder="펫을 선택해 전용 이미지를 확인하세요", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.menu_view.owner_id:
            await interaction.response.send_message("이 펫 메뉴는 명령어를 실행한 생존자만 사용할 수 있습니다.", ephemeral=True)
            return
        name = self.values[0]
        record = self.menu_view.collection.get(name, {}) if isinstance(self.menu_view.collection, dict) else {}
        stage = _clamp_stage(record.get("evolution", 0))
        embed, file = self.menu_view.build_card(name, stage, mode="shop")
        kwargs = {"embed": embed, "ephemeral": True}
        if file is not None:
            kwargs["file"] = file
        await interaction.response.send_message(**kwargs)


class PetBrowseView(discord.ui.View):
    def __init__(
        self,
        *,
        owner_id: int,
        pet_db: Mapping[str, Mapping[str, Any]],
        collection: Mapping[str, Mapping[str, Any]],
        display_name: Callable[[str, Mapping[str, Any]], str],
        power: Callable[..., int],
        user: Mapping[str, Any],
    ) -> None:
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.pet_db = pet_db
        self.collection = collection
        self.display_name = display_name
        self.power = power
        self.user = user
        self.add_item(PetBrowseSelect(self))

    def build_card(self, pet_name: str, stage: int, mode: str = "shop"):
        info = self.pet_db[pet_name]
        record = self.collection.get(pet_name, {"level": 1, "friendship": 0, "evolution": stage})
        display = self.display_name(pet_name, record)
        owned = pet_name in self.collection
        status = "✅ 보유 중" if owned else f"🥫 식량 {int(info.get('price', 0)):,}개"
        embed = discord.Embed(
            title=f"{info.get('emoji', '🐾')} {display}",
            description=str(info.get("desc", "귀여운 생존 동료입니다.")),
            color=RARITY_COLORS.get(str(info.get("rarity", "일반")), 0xB8C7D6),
        )
        embed.add_field(name="등급 · 상태", value=f"**{info.get('rarity', '일반')} · {status}**", inline=True)
        embed.add_field(name="진화 단계", value=f"**{stage}/2**", inline=True)
        embed.add_field(name="기본 전투력", value=f"**+{int(info.get('power', 0))}**", inline=True)
        embed.add_field(name=f"고유 능력 · {info.get('skill', '동행')}", value=str(info.get("skill_desc", "함께 생존합니다."))[:1024], inline=False)
        if owned:
            try:
                current_power = self.power(self.user, pet_name)
            except Exception:
                current_power = int(info.get("power", 0))
            embed.add_field(
                name="현재 성장",
                value=f"Lv.{int(record.get('level', 1))} · 친밀도 {int(record.get('friendship', 0))} · 전투력 +{current_power}",
                inline=False,
            )
        file = pet_file(pet_name, stage, "browse")
        if file is not None:
            embed.set_image(url=f"attachment://{file.filename}")
        embed.set_footer(text="ABADDON PET VISUALS v6.3.4 · 19종 동료의 귀여운 3단 진화 이미지")
        return embed, file


async def send_pet_visual(
    ctx: commands.Context,
    *,
    pet_name: str,
    record: Optional[Mapping[str, Any]] = None,
    mode: str = "info",
    extra: str = "",
) -> Optional[discord.Message]:
    bot = ctx.bot
    pet_db = getattr(bot, "v634_pet_db", {})
    info = pet_db.get(pet_name)
    if not info:
        return None
    record = record or {"level": 1, "friendship": 0, "evolution": 0}
    stage = _clamp_stage(record.get("evolution", 0))
    display_fn = getattr(bot, "v634_pet_display_name", None)
    display = display_fn(pet_name, record) if callable(display_fn) else pet_name
    power_fn = getattr(bot, "v634_pet_power", None)
    try:
        user = getattr(bot, "v634_get_user")(ctx.author.id)
        current_power = power_fn(user, pet_name) if callable(power_fn) else int(info.get("power", 0))
    except Exception:
        current_power = int(info.get("power", 0))
    embed = discord.Embed(
        title=MODE_TITLES.get(mode, MODE_TITLES["info"]),
        description=f"{info.get('emoji', '🐾')} **{display}**\n{extra or info.get('desc', '')}",
        color=RARITY_COLORS.get(str(info.get("rarity", "일반")), 0xB8C7D6),
    )
    embed.add_field(name="등급 · 진화", value=f"**{info.get('rarity', '일반')} · {stage}/2**", inline=True)
    embed.add_field(name="레벨 · 친밀도", value=f"**Lv.{int(record.get('level', 1))} · {int(record.get('friendship', 0))}**", inline=True)
    embed.add_field(name="전투력", value=f"**+{current_power}**", inline=True)
    embed.add_field(name=f"고유 능력 · {info.get('skill', '동행')}", value=str(info.get("skill_desc", "함께 생존합니다."))[:1024], inline=False)
    file = pet_file(pet_name, stage, mode)
    if file is not None:
        embed.set_image(url=f"attachment://{file.filename}")
    embed.set_footer(text="ABADDON PET VISUALS v6.3.4 · 19종 동료 · 성장과 진화에 따라 전용 이미지가 변경됩니다")
    kwargs = {"embed": embed}
    if file is not None:
        kwargs["file"] = file
    return await ctx.send(**kwargs)


async def send_pet_shop(ctx: commands.Context) -> Optional[discord.Message]:
    bot = ctx.bot
    pet_db = getattr(bot, "v634_pet_db", {})
    get_user = getattr(bot, "v634_get_user", None)
    ensure_collection = getattr(bot, "v634_ensure_pet_collection", None)
    if not pet_db or not callable(get_user) or not callable(ensure_collection):
        return None
    user = get_user(ctx.author.id)
    collection = ensure_collection(user)
    first = next(iter(pet_db))
    view = PetBrowseView(
        owner_id=ctx.author.id,
        pet_db=pet_db,
        collection=collection,
        display_name=getattr(bot, "v634_pet_display_name"),
        power=getattr(bot, "v634_pet_power"),
        user=user,
    )
    embed, file = view.build_card(first, _clamp_stage(collection.get(first, {}).get("evolution", 0)), mode="shop")
    embed.title = "🐾 펫 상점 이미지 도감"
    embed.description = "드롭다운에서 펫을 고르면 기본형과 현재 진화 외형을 확인할 수 있습니다.\n\n" + embed.description
    kwargs = {"embed": embed, "view": view}
    if file is not None:
        kwargs["file"] = file
    return await ctx.send(**kwargs)


def register_v634_pet_visuals(
    bot: commands.Bot,
    get_user: Callable[[int], Dict[str, Any]],
    pet_db: Mapping[str, Mapping[str, Any]],
    ensure_pet_collection: Callable[[Dict[str, Any]], Dict[str, Any]],
    get_pet_display_name: Callable[[str, Mapping[str, Any]], str],
    get_pet_power: Callable[..., int],
) -> None:
    bot.v634_get_user = get_user
    bot.v634_pet_db = pet_db
    bot.v634_ensure_pet_collection = ensure_pet_collection
    bot.v634_pet_display_name = get_pet_display_name
    bot.v634_pet_power = get_pet_power
    bot.v634_send_pet_visual = send_pet_visual
    bot.v634_send_pet_shop = send_pet_shop
    bot.v634_pet_asset_path = pet_asset_path
    bot.v634_pet_visual_version = VERSION
