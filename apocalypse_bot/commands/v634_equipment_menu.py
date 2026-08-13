from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v600_game_center import _safe_select_options, _safe_embed, _safe_view

VERSION = "6.3.4"
PAGE_SIZE = 5

CATEGORY_LABELS = {
    "equipped": "현재 장착 현황",
    "owned": "보유 장비",
    "all": "전체 장비",
    "slot:무기": "슬롯 · 무기",
    "slot:방어구": "슬롯 · 방어구",
    "slot:머리": "슬롯 · 머리",
    "slot:장갑": "슬롯 · 장갑",
    "slot:신발": "슬롯 · 신발",
    "slot:반지": "슬롯 · 반지",
    "slot:목걸이": "슬롯 · 목걸이",
    "tier:일반": "등급 · 일반",
    "tier:고급": "등급 · 고급",
    "tier:희귀": "등급 · 희귀",
    "tier:영웅": "등급 · 영웅",
    "tier:전설": "등급 · 전설",
    "tier:신화": "등급 · 신화",
    "tier:유일": "등급 · 유일",
}


class EquipmentSearchModal(discord.ui.Modal, title="장비 검색"):
    query = discord.ui.TextInput(label="장비 이름", placeholder="예: 레일건, 장갑, 코어", min_length=1, max_length=30)

    def __init__(self, menu: "EquipmentMenuView") -> None:
        super().__init__()
        self.menu = menu

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.menu.owner_id:
            await interaction.response.send_message("이 장비 메뉴는 명령어를 실행한 생존자만 사용할 수 있습니다.", ephemeral=True)
            return
        q = str(self.query.value).strip().lower().replace(" ", "")
        matches = [name for name in self.menu.all_items if q in name.lower().replace(" ", "")]
        if not matches:
            await interaction.response.send_message(f"`{self.query.value}`와 일치하는 장비를 찾지 못했습니다.", ephemeral=True)
            return
        if len(matches) == 1 or matches[0].lower().replace(" ", "") == q:
            await self.menu.send_item_card(interaction, matches[0])
            return
        lines = []
        for name in matches[:10]:
            tier, info = self.menu.find_item(name)
            lines.append(f"• {self.menu.tier_emoji.get(tier, '⚪')} **{name}** · {tier} · {self.menu.get_item_slot(name)}")
        suffix = f"\n외 {len(matches)-10}종" if len(matches) > 10 else ""
        await interaction.response.send_message("🔎 **검색 결과**\n" + "\n".join(lines) + suffix, ephemeral=True)


class CategorySelect(discord.ui.Select):
    def __init__(self, menu: "EquipmentMenuView") -> None:
        self.menu = menu
        options = [
            discord.SelectOption(label="현재 장착 현황", value="equipped", emoji="⚔️"),
            discord.SelectOption(label="보유 장비", value="owned", emoji="🎒"),
            discord.SelectOption(label="전체 장비 70종", value="all", emoji="📚"),
        ]
        for slot, emoji in [("무기","🗡️"),("방어구","🛡️"),("머리","🪖"),("장갑","🧤"),("신발","🥾"),("반지","💍"),("목걸이","📿")]:
            options.append(discord.SelectOption(label=f"슬롯 · {slot}", value=f"slot:{slot}", emoji=emoji))
        for tier, emoji in [("일반","⚪"),("고급","🟢"),("희귀","🔵"),("영웅","🟣"),("전설","🟠"),("신화","🔴"),("유일","🌈")]:
            options.append(discord.SelectOption(label=f"등급 · {tier}", value=f"tier:{tier}", emoji=emoji))
        super().__init__(placeholder="장비 목록 분류를 선택하세요", options=_safe_select_options(options), min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.menu.check_owner(interaction):
            return
        self.menu.category = self.values[0]
        self.menu.page = 0
        self.menu.refresh_item_select()
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            await interaction.edit_original_response(embed=_safe_embed(self.menu.build_embed()), view=_safe_view(self.menu))
        except discord.NotFound:
            try:
                await interaction.followup.send("🫧 장비 메뉴가 만료되었습니다. `!장비`를 다시 열어주세요.", ephemeral=True)
            except Exception:
                pass


class ItemSelect(discord.ui.Select):
    def __init__(self, menu: "EquipmentMenuView") -> None:
        self.menu = menu
        super().__init__(placeholder="현재 페이지에서 장비를 선택하세요", options=[discord.SelectOption(label="장비 없음", value="__none__")], min_values=1, max_values=1, row=1, disabled=True)
        self.sync_options()

    def sync_options(self) -> None:
        items = self.menu.page_items()
        if not items:
            self.options = [discord.SelectOption(label="표시할 장비가 없습니다", value="__none__")]
            self.disabled = True
            return
        opts = []
        for name in items:
            tier, _ = self.menu.find_item(name)
            level = int(self.menu.user.get("enhancements", {}).get(name, 0))
            opts.append(
                discord.SelectOption(
                    label=f"{name} +{level}"[:100],
                    value=name,
                    emoji=self.menu.tier_emoji.get(tier, "⚪"),
                    description=f"{tier} · {self.menu.get_item_slot(name)}"[:100],
                )
            )
        self.options = _safe_select_options(opts)
        self.disabled = False

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await self.menu.check_owner(interaction):
            return
        value = self.values[0]
        if value == "__none__":
            await interaction.response.defer()
            return
        await self.menu.send_item_card(interaction, value)


class EquipmentMenuView(discord.ui.View):
    def __init__(
        self,
        *,
        owner_id: int,
        user: Dict[str, Any],
        item_db: Mapping[str, Mapping[str, Mapping[str, Any]]],
        tier_order: Sequence[str],
        tier_emoji: Mapping[str, str],
        equipment_slots: Sequence[str],
        find_item: Callable[[str], Tuple[Optional[str], Optional[Mapping[str, Any]]]],
        get_item_slot: Callable[[str], str],
        get_item_stats: Callable[[str], Mapping[str, Any]],
        equipment_totals: Callable[[Dict[str, Any]], Mapping[str, Any]],
        build_visual_file: Optional[Callable[..., Any]],
    ) -> None:
        super().__init__(timeout=240)
        self.owner_id = owner_id
        self.user = user
        self.item_db = item_db
        self.tier_order = list(tier_order)
        self.tier_emoji = tier_emoji
        self.equipment_slots = list(equipment_slots)
        self.find_item = find_item
        self.get_item_slot = get_item_slot
        self.get_item_stats = get_item_stats
        self.equipment_totals = equipment_totals
        self.build_visual_file = build_visual_file
        self.category = "equipped"
        self.page = 0
        self.all_items = [name for tier in self.tier_order for name in self.item_db.get(tier, {})]
        self.category_select = CategorySelect(self)
        self.item_select = ItemSelect(self)
        self.add_item(self.category_select)
        self.add_item(self.item_select)

    async def check_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("이 장비 메뉴는 명령어를 실행한 생존자만 사용할 수 있습니다.", ephemeral=True)
        return False

    def filtered_items(self) -> List[str]:
        if self.category == "equipped":
            return [self.user.get("equipment", {}).get(slot) for slot in self.equipment_slots if self.user.get("equipment", {}).get(slot)]
        if self.category == "owned":
            return [name for name in self.user.get("inventory", []) if self.find_item(name)[1]]
        if self.category == "all":
            return list(self.all_items)
        if self.category.startswith("slot:"):
            slot = self.category.split(":", 1)[1]
            return [name for name in self.all_items if self.get_item_slot(name) == slot]
        if self.category.startswith("tier:"):
            tier = self.category.split(":", 1)[1]
            return list(self.item_db.get(tier, {}).keys())
        return []

    def max_page(self) -> int:
        count = len(self.filtered_items())
        return max(0, (count - 1) // PAGE_SIZE)

    def page_items(self) -> List[str]:
        items = self.filtered_items()
        self.page = max(0, min(self.page, self.max_page()))
        start = self.page * PAGE_SIZE
        return items[start:start + PAGE_SIZE]

    def refresh_item_select(self) -> None:
        self.item_select.sync_options()
        self.previous.disabled = self.page <= 0
        self.next.disabled = self.page >= self.max_page()

    def build_embed(self) -> discord.Embed:
        items = self.page_items()
        total = len(self.filtered_items())
        title = CATEGORY_LABELS.get(self.category, "장비 메뉴")
        embed = discord.Embed(
            title=f"⚔️ {title}",
            description="분류 드롭다운과 페이지 버튼으로 장비를 확인하고, 아래 장비 선택 메뉴에서 상세 이미지와 능력치를 열 수 있습니다.",
            color=0xB89958,
        )
        if self.category == "equipped":
            totals = self.equipment_totals(self.user)
            embed.add_field(
                name="📊 장착 능력치 합계",
                value=(
                    f"공격력 +{totals.get('공격력', 0)} · 방어력 +{totals.get('방어력', 0)}\n"
                    f"치명타 +{totals.get('치명타', 0)}% · 회피 +{totals.get('회피', 0)}%\n"
                    f"감염저항 +{totals.get('감염저항', 0)}% · 행운 +{totals.get('행운', 0)}"
                ),
                inline=False,
            )
        if not items:
            embed.add_field(name="목록", value="표시할 장비가 없습니다.", inline=False)
        else:
            lines = []
            equipped = {x for x in self.user.get("equipment", {}).values() if x}
            for name in items:
                tier, info = self.find_item(name)
                level = int(self.user.get("enhancements", {}).get(name, 0))
                state = " · ✅ 장착" if name in equipped else (" · 🎒 보유" if name in self.user.get("inventory", []) else "")
                lines.append(
                    f"{self.tier_emoji.get(tier, '⚪')} **{name} +{level}** · {tier} · {self.get_item_slot(name)}{state}\n"
                    f"└ {str((info or {}).get('desc', ''))}"
                )
            embed.add_field(name=f"장비 {total}종", value="\n".join(lines)[:1024], inline=False)
        embed.set_footer(text=f"ABADDON EQUIPMENT MENU v6.3.4 · {self.page + 1}/{self.max_page() + 1} 페이지 · 기존 !장비목록/!인벤토리 명령 유지")
        return embed

    async def send_item_card(self, interaction: discord.Interaction, item_name: str) -> None:
        tier, info = self.find_item(item_name)
        if not info:
            await interaction.response.send_message("장비 정보를 찾지 못했습니다.", ephemeral=True)
            return
        slot = self.get_item_slot(item_name)
        level = int(self.user.get("enhancements", {}).get(item_name, 0))
        stats = self.get_item_stats(item_name)
        equipped = item_name in self.user.get("equipment", {}).values()
        owned = item_name in self.user.get("inventory", [])
        stat_text = " · ".join(f"{k} +{v}{'%' if k in {'치명타','회피','감염저항'} else ''}" for k, v in stats.items() if v) or "특수 능력치 없음"
        embed = discord.Embed(
            title=f"{self.tier_emoji.get(tier, '⚪')} {item_name} +{level}",
            description=str(info.get("desc", "")),
            color=0xB89958,
        )
        embed.add_field(name="등급 · 슬롯", value=f"**{tier} · {slot}**", inline=True)
        embed.add_field(name="기본 전투력", value=f"**+{int(info.get('power', 0))}**", inline=True)
        embed.add_field(name="보유 · 장착", value=f"**{'보유' if owned else '미보유'} · {'장착 중' if equipped else '미장착'}**", inline=True)
        embed.add_field(name="능력치", value=stat_text[:1024], inline=False)
        progress = max(0, min(20, int(level)))
        filled = int(round(progress / 20 * 10))
        embed.add_field(name="✨ 강화 진행", value=f"{'🟨' * filled}{'⬛' * (10-filled)} **{progress}/20**", inline=False)
        file = None
        if callable(self.build_visual_file):
            try:
                file = await self.build_visual_file(item_name, tier or "일반", slot, True, level, "menu")
            except Exception:
                file = None
        if file is not None:
            embed.set_image(url=f"attachment://{file.filename}")
        embed.set_footer(text="장착: !장착 아이템명 · 강화: !강화 아이템명 · 외형: !장비외형 아이템명")
        kwargs = {"embed": embed, "ephemeral": True}
        if file is not None:
            kwargs["file"] = file
        await interaction.response.send_message(**kwargs)

    @discord.ui.button(label="이전", emoji="◀️", style=discord.ButtonStyle.secondary, row=2)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self.check_owner(interaction):
            return
        self.page = max(0, self.page - 1)
        self.refresh_item_select()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="다음", emoji="▶️", style=discord.ButtonStyle.secondary, row=2)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self.check_owner(interaction):
            return
        self.page = min(self.max_page(), self.page + 1)
        self.refresh_item_select()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="장비 검색", emoji="🔎", style=discord.ButtonStyle.primary, row=2)
    async def search(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self.check_owner(interaction):
            return
        await interaction.response.send_modal(EquipmentSearchModal(self))



def register_v634_equipment_menu(
    bot: commands.Bot,
    get_user: Callable[[int], Dict[str, Any]],
    check_registered: Callable[..., Any],
    item_db: Mapping[str, Mapping[str, Mapping[str, Any]]],
    tier_order: Sequence[str],
    tier_emoji: Mapping[str, str],
    equipment_slots: Sequence[str],
    find_item: Callable[[str], Tuple[Optional[str], Optional[Mapping[str, Any]]]],
    get_item_slot: Callable[[str], str],
    get_item_stats: Callable[[str], Mapping[str, Any]],
    equipment_totals: Callable[[Dict[str, Any]], Mapping[str, Any]],
) -> None:
    command = bot.get_command("장비")
    if command is not None:
        async def v634_equipment(ctx: commands.Context) -> None:
            if not await check_registered(ctx):
                return
            user = get_user(ctx.author.id)
            view = EquipmentMenuView(
                owner_id=ctx.author.id,
                user=user,
                item_db=item_db,
                tier_order=tier_order,
                tier_emoji=tier_emoji,
                equipment_slots=equipment_slots,
                find_item=find_item,
                get_item_slot=get_item_slot,
                get_item_stats=get_item_stats,
                equipment_totals=equipment_totals,
                build_visual_file=getattr(bot, "v633_build_named_equipment_file", None),
            )
            view.refresh_item_select()
            await ctx.send(embed=view.build_embed(), view=view)
        command.callback = v634_equipment
        command.help = "장착 현황·보유 장비·전체 장비를 드롭다운과 검색으로 확인합니다."
        command.description = command.help

    patch_notes = bot.get_command("패치노트")
    if patch_notes is not None:
        async def v634_patch_notes(ctx: commands.Context) -> None:
            await ctx.send(
                "🐾 **ABADDON v6.3.4 — 귀여운 펫 비주얼 & 장비 메뉴 패치**\n"
                "• 펫 7종의 기본·1차·최종 진화 이미지 21장 적용\n"
                "• 펫 상점·정보·구매·장착·훈련·먹이·모험·진화 결과에 현재 펫 이미지 표시\n"
                "• `!장비`에 장착/보유/전체/슬롯/등급 드롭다운과 페이지·검색·상세 이미지 기능 추가\n"
                "• 기존 펫 능력·가격·성장 조건과 장비 능력치·가격·강화 규칙은 변경하지 않음"
            )
        patch_notes.callback = v634_patch_notes
        patch_notes.help = "ABADDON 최신 통합 패치 내용을 확인합니다."
        patch_notes.description = patch_notes.help

    bot.v634_equipment_menu_version = VERSION
