from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands import v631_life_visuals as stage1

VERSION = "6.5.3"
ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets" / "v632"
ENCOUNTER_CHANCE = 0.10
SPECIAL_NEGOTIATION_CHANCE = 0.10
SPECIAL_NEGOTIATION_MIN = 5_000
SPECIAL_NEGOTIATION_MAX = 20_000

TIP_POOLS: Mapping[str, Sequence[str]] = {
    "fishing": (
        "낚시와 광산은 서로 다른 사용자별 2분 쿨타임을 사용합니다.",
        "수면의 비정상적인 파문은 희귀 어종이나 매복 신호일 수 있습니다.",
        "랜덤 인카운트 성공 시 낮은 확률로 거래 가능한 고가 장비가 나옵니다.",
    ),
    "mining": (
        "광산은 낚시와 쿨타임을 공유하지 않습니다.",
        "연속 낙석음이 들리면 광맥보다 퇴로 확보가 먼저입니다.",
        "희귀 거래 장비는 기존 거래소의 `!판매 아이템명 가격`으로 등록할 수 있습니다.",
    ),
    "coin": (
        "코인 탐색은 1분마다 가능하며 하루 30회, KST 자정에 초기화됩니다.",
        "실패 수리비는 현재 잔액을 넘지 않습니다.",
        "코인 탐색 인카운트는 기존 암시장 코인 결과를 덮어쓰지 않습니다.",
    ),
    "exploration": (
        "탐색은 도박 콘텐츠이며 방향과 배팅액을 먼저 정합니다.",
        "랜덤 인카운트는 기존 배팅 승패가 끝난 뒤 별도로 발생합니다.",
        "카지노 드롭다운과 기존 44% 성공 판정은 그대로 유지됩니다.",
    ),
    "support": (
        "돈주세요는 1분마다 가능하며 하루 50회, KST 자정에 초기화됩니다.",
        "특별 교섭은 정상 지원 이후 낮은 확률로 나타나는 선택형 이벤트입니다.",
        "교섭 성공 시 기본 지원금과 별도로 5,000~20,000 식량을 추가로 받습니다.",
    ),
}

_RECENT_ASSETS: Dict[str, List[str]] = {}
FIXED_ASSET_MAP: Mapping[str, str] = {
    # 채굴·도박 탐색은 기존 전용 장면 유지
    "activities/mining/encounter": "activities/coin/encounter/01.jpg",
    "activities/mining/encounter_success": "activities/coin/encounter_success/01.jpg",
    "activities/mining/encounter_failure": "activities/mining/encounter_failure/01.jpg",
    "activities/mining/success": "activities/coin/success/01.jpg",
    "activities/mining/failure": "activities/mining/encounter_failure/01.jpg",
    "activities/mining/rare": "activities/coin/rare/01.jpg",
    "activities/exploration/encounter": "activities/support/encounter/01.jpg",
    "activities/exploration/encounter_failure": "activities/support/encounter_failure/01.jpg",
    "activities/exploration/failure": "activities/support/failure/02.jpg",
    "activities/exploration/success": "activities/support/encounter_success/02.jpg",
    "activities/exploration/rare": "activities/support/rare/01.jpg",
}

CATEGORY_GALLERY_POOLS: Mapping[str, str] = {
    "activities/fishing/": "activities/fishing/gallery",
    "activities/coin/": "activities/coin/gallery",
    "activities/support/": "activities/support/gallery",
}



def random_tip(activity: str) -> str:
    return random.choice(tuple(TIP_POOLS.get(activity) or ("기존 명령 규칙을 유지합니다.",)))


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
    return discord.File(str(path), filename=f"abaddon_v632_{safe}")


def _set_image(embed: discord.Embed, path: Optional[Path]) -> Optional[discord.File]:
    if path is None or not path.is_file():
        return None
    file = _discord_file(path)
    embed.set_image(url=f"attachment://{file.filename}")
    return file


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
    negotiation: bool = False


LABELS: Mapping[str, Tuple[str, str]] = {
    "fishing": ("🎣", "낚시"),
    "mining": ("⛏️", "광산"),
    "coin": ("🪙", "코인 탐색"),
    "exploration": ("🚪", "도박 탐색"),
    "support": ("🤝", "특별 교섭"),
}

ENCOUNTERS: Tuple[Encounter, ...] = (
    Encounter("fishing_mutant_school", "fishing", "danger", "돌연변이 어군", "수면 아래 거대한 그림자들이 낚싯줄을 따라 원을 그립니다.", (("줄을 짧게 감는다", "🎣", "safe"), ("미끼를 바꿔 유인한다", "🪱", "help"), ("대형 개체를 노린다", "🦈", "risk"))),
    Encounter("fishing_waterproof_cache", "fishing", "rare", "방수 보급함", "낚싯바늘이 물고기 대신 잠긴 방수 상자에 걸렸습니다.", (("매듭부터 보강한다", "🪢", "safe"), ("부표를 달아 함께 끌어낸다", "🛟", "help"), ("한 번에 끌어올린다", "💪", "risk"))),
    Encounter("fishing_raider_boat", "fishing", "common", "버려진 약탈자 보트", "갈대 사이에서 작은 보트와 봉인된 물자통을 발견했습니다.", (("주변부터 확인한다", "🔭", "safe"), ("보트 엔진을 점검한다", "🔧", "help"), ("물자통을 즉시 연다", "📦", "risk"))),
    Encounter("mining_resonant_vein", "mining", "rare", "공명하는 광맥", "곡괭이를 댈 때마다 푸른 광석이 낮은 진동음을 냅니다.", (("외곽만 채굴한다", "⛏️", "safe"), ("지지대를 설치한다", "🧱", "help"), ("핵심 광맥을 깨뜨린다", "💎", "risk"))),
    Encounter("mining_machine_vault", "mining", "common", "폐쇄된 기계 금고", "광산 관리실 아래에서 전력이 남은 부품 금고를 찾았습니다.", (("회로를 차단한다", "🔌", "safe"), ("정비 모드로 연다", "🛠️", "help"), ("잠금핀을 폭파한다", "💥", "risk"))),
    Encounter("mining_cave_stalker", "mining", "danger", "갱도 추적자", "어둠 속 발톱 자국이 새 광맥까지 이어지고 있습니다.", (("소음을 줄여 우회한다", "🤫", "safe"), ("조명탄으로 몰아낸다", "🔥", "help"), ("둥지까지 추적한다", "⚔️", "risk"))),
    Encounter("coin_ghost_wallet", "coin", "rare", "유령 지갑 신호", "폐서버에서 소유자가 사라진 고가 자산 서명이 감지됩니다.", (("읽기 전용으로 복구한다", "🔎", "safe"), ("분산 노드로 검증한다", "🖥️", "help"), ("즉시 지갑을 해제한다", "🔓", "risk"))),
    Encounter("coin_broker_offer", "coin", "common", "데이터 브로커의 제안", "익명 브로커가 희귀 자산 위치와 교환 조건을 전송했습니다.", (("소액 정보만 산다", "🪙", "safe"), ("서명을 상호 검증한다", "🤝", "help"), ("전체 좌표를 구매한다", "📡", "risk"))),
    Encounter("coin_traceback", "coin", "danger", "역추적 신호", "스캐너 뒤편에서 정체불명의 접속이 역으로 따라붙었습니다.", (("연결을 즉시 끊는다", "✂️", "safe"), ("가짜 경로로 유도한다", "🛰️", "help"), ("공격 노드를 역해킹한다", "⚡", "risk"))),
    Encounter("explore_hidden_chamber", "exploration", "rare", "숨겨진 도박방", "배팅 통로 뒤쪽에서 오래된 승자 전용 보관실을 발견했습니다.", (("입구만 조사한다", "🔍", "safe"), ("기록 장치를 복구한다", "📼", "help"), ("금고를 강제로 연다", "🔨", "risk"))),
    Encounter("explore_wounded_runner", "exploration", "common", "부상당한 운반책", "도박 통로에서 물자 가방을 든 운반책이 도움을 요청합니다.", (("응급 처치만 한다", "🩹", "safe"), ("안전 구역까지 호위한다", "🤝", "help"), ("추격자의 물자를 노린다", "🎯", "risk"))),
    Encounter("explore_double_trap", "exploration", "danger", "이중 와이어 덫", "첫 번째 함정 뒤에 더 정교한 압력판이 숨겨져 있습니다.", (("되돌아간다", "↩️", "safe"), ("표식하며 해체한다", "🧰", "help"), ("도약해 통과한다", "🏃", "risk"))),
    Encounter("support_special_negotiation", "support", "rare", "긴급 특별 교섭", "보급 담당자가 추가 배급 심사를 열었습니다. 기본 지원금은 이미 확보된 상태입니다.", (("정식 활동 기록을 제출한다", "📋", "safe"), ("보급 중개인을 설득한다", "🤝", "help"), ("최대 배급을 강하게 요청한다", "📢", "risk")), True),
)


def _profile(user: Dict[str, Any]) -> Dict[str, Any]:
    return stage1._ensure_profile(user)


def _resource(activity: str) -> str:
    return {"fishing": "물고기", "mining": "광석", "coin": "고철", "exploration": "고철"}.get(activity, "고철")


def _apply(user: Dict[str, Any], profile: Dict[str, Any], encounter: Encounter, mode: str) -> Tuple[str, int]:
    chance = {"safe": 0.84, "help": 0.72, "risk": 0.54}.get(mode, 0.65)
    if encounter.rarity == "danger": chance -= 0.08
    if encounter.rarity == "rare": chance -= 0.04
    success = random.random() < max(0.25, min(0.93, chance))
    if encounter.negotiation:
        if not success:
            return "교섭이 결렬됐습니다. 기본 지원금은 그대로 유지되며 추가 손실은 없습니다.", 0
        room = max(0, stage1.ENCOUNTER_REWARD_CAP - int(profile.get("daily_reward", 0)))
        if room < SPECIAL_NEGOTIATION_MIN:
            return "오늘 인카운트 보상 상한에 도달해 추가 배급은 다음 날 다시 심사됩니다.", 0
        reward = random.randint(SPECIAL_NEGOTIATION_MIN, min(SPECIAL_NEGOTIATION_MAX, room))
        user["balance"] = int(user.get("balance", 0)) + reward
        user.setdefault("stats", {}).setdefault("earned", 0)
        user["stats"]["earned"] = int(user["stats"].get("earned", 0)) + reward
        profile["daily_reward"] = int(profile.get("daily_reward", 0)) + reward
        valuable = stage1._try_valuable_item(user, profile)
        return f"특별 교섭에 성공했습니다. 💰 추가 식량 +{reward:,}{valuable}", reward

    if success:
        room = max(0, stage1.ENCOUNTER_REWARD_CAP - int(profile.get("daily_reward", 0)))
        reward = min(room, random.randint(250, 750 if mode == "safe" else 1_250 if mode == "help" else 2_100))
        resource = _resource(encounter.activity)
        amount = random.randint(1, 3 if mode == "safe" else 5 if mode == "help" else 8)
        user["balance"] = int(user.get("balance", 0)) + reward
        user.setdefault("stats", {}).setdefault("earned", 0)
        user["stats"]["earned"] = int(user["stats"].get("earned", 0)) + reward
        user.setdefault("resources", {})
        user["resources"][resource] = int(user["resources"].get(resource, 0)) + amount
        profile["daily_reward"] = int(profile.get("daily_reward", 0)) + reward
        valuable = stage1._try_valuable_item(user, profile)
        return f"선택 성공! 💰 식량 +{reward:,} · 📦 {resource} +{amount}{valuable}", reward

    balance = max(0, int(user.get("balance", 0)))
    loss_max = 250 if mode == "safe" else 500 if mode == "help" else 900
    loss = min(balance, random.randint(40, loss_max))
    user["balance"] = balance - loss
    return f"현장 변수를 피하지 못하고 철수했습니다. 💸 식량 -{loss:,}", -loss


class EncounterView(discord.ui.View):
    def __init__(self, owner_id: int, encounter: Encounter, user: Dict[str, Any], save_data: Callable[[], None]):
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
                await self.resolve(interaction, selected_mode, selected_label)
            button.callback = callback
            self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) != self.owner_id:
            await interaction.response.send_message("이 인카운트는 발견한 생존자만 선택할 수 있습니다.", ephemeral=True)
            return False
        return True

    async def resolve(self, interaction: discord.Interaction, mode: str, label: str) -> None:
        if self.resolved:
            await interaction.response.send_message("이미 처리된 인카운트입니다.", ephemeral=True)
            return
        self.resolved = True
        profile = _profile(self.user)
        text, delta = _apply(self.user, profile, self.encounter, mode)
        profile.setdefault("choices", {})[self.encounter.encounter_id] = int(profile.setdefault("choices", {}).get(self.encounter.encounter_id, 0)) + 1
        profile["last_at"] = datetime.now(timezone.utc).isoformat()
        self.save_data()
        for item in self.children: item.disabled = True
        emoji, label_text = LABELS[self.encounter.activity]
        color = discord.Color.green() if delta > 0 else discord.Color.orange() if delta == 0 else discord.Color.red()
        embed = discord.Embed(title=f"{emoji} 인카운트 결과 · {self.encounter.title}", description=f"선택: **{label}**\n\n{text}", color=color, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="💳 현재 잔액", value=f"**{int(self.user.get('balance', 0)):,} 식량**", inline=True)
        embed.add_field(name="📚 도감", value=f"`!인카운트도감` · {label_text}", inline=True)
        embed.add_field(name="💡 TIP", value=random_tip(self.encounter.activity), inline=False)
        relative = f"activities/{self.encounter.activity}/encounter_success" if delta > 0 else f"activities/{self.encounter.activity}/encounter_failure"
        # coin/exploration have fewer encounter-result images; fall back to existing result folders.
        if not _asset_files(relative):
            relative = f"activities/{self.encounter.activity}/{'success' if delta > 0 else 'failure'}"
        file = _set_image(embed, pick_asset(relative))
        kwargs: Dict[str, Any] = {"embed": embed, "view": self}
        if file is not None: kwargs["attachments"] = [file]
        try:
            await interaction.response.edit_message(**kwargs)
        except (discord.HTTPException, TypeError):
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=self)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
        stage1._ACTIVE_USERS.discard(self.owner_id)

    async def on_timeout(self) -> None:
        for item in self.children: item.disabled = True
        stage1._ACTIVE_USERS.discard(self.owner_id)
        if self.message is not None:
            try: await self.message.edit(view=self)
            except (discord.Forbidden, discord.HTTPException, AttributeError): pass


async def _send_encounter(ctx: commands.Context, activity: str, user: Dict[str, Any], save_data: Callable[[], None], encounter: Encounter) -> Optional[discord.Message]:
    uid = int(ctx.author.id)
    if uid in stage1._ACTIVE_USERS: return None
    profile = _profile(user)
    if int(profile.get("daily_count", 0)) >= stage1.ENCOUNTER_DAILY_LIMIT: return None
    profile["daily_count"] = int(profile.get("daily_count", 0)) + 1
    profile["total"] = int(profile.get("total", 0)) + 1
    profile.setdefault("seen", [])
    if encounter.encounter_id not in profile["seen"]: profile["seen"].append(encounter.encounter_id)
    profile.setdefault("recent", []).append(encounter.encounter_id)
    del profile["recent"][:-5]
    save_data()
    stage1._ACTIVE_USERS.add(uid)
    emoji, label = LABELS[activity]
    rarity = {"common": "일반", "rare": "희귀", "danger": "위험"}[encounter.rarity]
    embed = discord.Embed(title=f"{emoji} 랜덤 인카운트 · {encounter.title}", description=f"**{label} 도중 예상치 못한 상황이 발생했습니다.**\n\n{encounter.description}", color=discord.Color.gold() if encounter.rarity == "rare" else discord.Color.red() if encounter.rarity == "danger" else discord.Color.blurple(), timestamp=datetime.now(timezone.utc))
    embed.add_field(name="희귀도", value=f"**{rarity}**", inline=True)
    embed.add_field(name="오늘 남은 조우", value=f"**{stage1.ENCOUNTER_DAILY_LIMIT - int(profile['daily_count'])}회**", inline=True)
    embed.add_field(name="선택 제한", value="**150초**", inline=True)
    if encounter.negotiation:
        embed.add_field(name="자동 판정", value=f"성공 시 **추가 {SPECIAL_NEGOTIATION_MIN:,}~{SPECIAL_NEGOTIATION_MAX:,} 식량** · 실패해도 기본 지원 유지", inline=False)
    embed.add_field(name="💡 TIP", value=random_tip(activity), inline=False)
    view = EncounterView(uid, encounter, user, save_data)
    try:
        message = await send_visual(ctx, embed, f"activities/{activity}/encounter", view=view)
    except Exception:
        stage1._ACTIVE_USERS.discard(uid)
        raise
    view.message = message
    return message


async def maybe_encounter(ctx: commands.Context, activity: str, user: Dict[str, Any], save_data: Callable[[], None]) -> Optional[discord.Message]:
    if activity not in {"fishing", "mining", "coin", "exploration"}: return None
    profile = _profile(user)
    if int(profile.get("daily_count", 0)) >= stage1.ENCOUNTER_DAILY_LIMIT or random.random() >= ENCOUNTER_CHANCE: return None
    candidates = [e for e in ENCOUNTERS if e.activity == activity and not e.negotiation]
    recent = set(profile.get("recent", [])[-2:])
    choices = [e for e in candidates if e.encounter_id not in recent] or candidates
    weights = [5 if e.rarity == "common" else 3 if e.rarity == "danger" else 2 for e in choices]
    return await _send_encounter(ctx, activity, user, save_data, random.choices(choices, weights=weights, k=1)[0])


async def maybe_special_negotiation(ctx: commands.Context, user: Dict[str, Any], save_data: Callable[[], None]) -> Optional[discord.Message]:
    profile = _profile(user)
    if int(profile.get("daily_count", 0)) >= stage1.ENCOUNTER_DAILY_LIMIT: return None
    if stage1.ENCOUNTER_REWARD_CAP - int(profile.get("daily_reward", 0)) < SPECIAL_NEGOTIATION_MIN: return None
    if random.random() >= SPECIAL_NEGOTIATION_CHANCE: return None
    encounter = next(e for e in ENCOUNTERS if e.encounter_id == "support_special_negotiation")
    return await _send_encounter(ctx, "support", user, save_data, encounter)


def register_v632_life_visuals(bot: commands.Bot, get_user: Callable[[int], Dict[str, Any]], check_registered: Callable[..., Any], save_data: Callable[[], None], item_db: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> None:
    # Replace stage1 codex with a combined stage1+stage2 view; no new top-level command is added.
    bot.remove_command("인카운트도감")

    @bot.command(name="인카운트도감", aliases=["조우도감", "랜덤이벤트도감"])
    async def encounter_codex(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        user = get_user(ctx.author.id)
        profile = _profile(user)
        seen = set(profile.get("seen", []))
        lines: List[str] = []
        combined = list(stage1.ENCOUNTERS) + list(ENCOUNTERS)
        label_map = dict(stage1.ACTIVITY_LABELS)
        label_map.update(LABELS)
        for activity, (emoji, label) in label_map.items():
            entries = [e for e in combined if e.activity == activity]
            found = [e.title for e in entries if e.encounter_id in seen]
            lines.append(f"{emoji} **{label}** {len(found)}/{len(entries)}\n└ " + (", ".join(found) if found else "아직 발견하지 못함"))
        embed = discord.Embed(title=f"📚 {ctx.author.display_name}의 인카운트 도감", description="\n\n".join(lines), color=discord.Color.dark_teal())
        embed.add_field(name="누적 조우", value=f"**{int(profile.get('total', 0))}회**", inline=True)
        embed.add_field(name="오늘 조우", value=f"**{int(profile.get('daily_count', 0))}/{stage1.ENCOUNTER_DAILY_LIMIT}회**", inline=True)
        embed.add_field(name="오늘 조우 수익", value=f"**{int(profile.get('daily_reward', 0)):,}/{stage1.ENCOUNTER_REWARD_CAP:,} 식량**", inline=False)
        embed.add_field(name="희귀 거래 장비", value=f"**{int(profile.get('daily_item_drops', 0))}/{stage1.VALUABLE_ITEM_DAILY_LIMIT}개**", inline=True)
        await send_visual(ctx, embed, "activities/mining/encounter")

    setattr(bot, "v632_send_visual", send_visual)
    setattr(bot, "v632_edit_visual", edit_visual)
    setattr(bot, "v632_tip", random_tip)
    setattr(bot, "v632_maybe_encounter", lambda ctx, activity, user: maybe_encounter(ctx, activity, user, save_data))
    setattr(bot, "v632_maybe_special_negotiation", lambda ctx, user: maybe_special_negotiation(ctx, user, save_data))
    setattr(bot, "v632_visual_version", VERSION)
