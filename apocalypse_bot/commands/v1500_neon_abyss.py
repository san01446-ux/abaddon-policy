from __future__ import annotations

"""ABADDON v15.0.0 NEON ABYSS.

A visual-first, guild-scoped expansion that layers on top of BLACK CITY without
invalidating older saves.  It provides:
- Korean-safe layered city maps and per-part decoration images
- staged Unicode-only action/reaction effects for existing commands
- dimension voyages, crews, raids, creator studio, ship and lineage summaries
- a context-aware bilingual conversation enhancer used by v620 dialogue
"""

import asyncio
import io
import json
import math
import os
import random
import re
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from apocalypse_bot.commands.v1010_companion_card_games import _ctx_locale, _t
from apocalypse_bot.commands.v1320_black_city_core import DISTRICTS, ensure_guild as ensure_black_city_guild, ensure_root as ensure_black_city_root

VERSION = "15.0.0"
DATA_KEY = "neon_abyss_v1500"
ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets" / "v1500"
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/nanum/NanumSquareRoundB.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/unfonts-core/UnDotum.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

COMPONENT_LABELS: Dict[str, Tuple[str, str]] = {
    "neon_gate": ("네온 관문", "Neon Gate"), "fountain": ("차원 분수", "Rift Fountain"),
    "gold_statue": ("황금 동상", "Golden Statue"), "street_lamp": ("가로등", "Street Lamp"),
    "night_tree": ("밤나무", "Night Tree"), "flowerbed": ("별빛 화단", "Starlight Garden"),
    "faction_banner": ("세력 깃발", "Faction Banner"), "bench": ("거리 벤치", "Street Bench"),
    "neon_train": ("네온 열차", "Neon Train"), "airship": ("감시 비행선", "Watch Airship"),
    "rift_portal": ("차원문", "Rift Portal"), "legend_trophy": ("전설 트로피", "Legend Trophy"),
    "fireworks": ("축제 불꽃", "Festival Fireworks"), "central_casino": ("중앙 카지노", "Central Casino"),
    "hwatu_street": ("화투 거리", "Hwatu Street"), "racetrack": ("심야 경마장", "Midnight Racetrack"),
    "prison": ("지하 감옥", "Underground Prison"), "harbor": ("검은 항구", "Black Harbor"),
    "demon_market": ("악마 시장", "Demon Market"), "ruin_ward": ("폐허 지구", "Ruin Ward"),
}

DISTRICT_COMPONENTS = {
    "중앙카지노": "central_casino", "화투거리": "hwatu_street", "심야경마장": "racetrack",
    "상업지구": "neon_train", "폐허지구": "ruin_ward", "항구": "harbor",
    "지하감옥": "prison", "악마시장": "demon_market", "월드관문": "rift_portal",
}

DIMENSIONS: Tuple[Dict[str, Any], ...] = (
    {"id": "blood_hwatu", "ko": "피의 달 화투왕국", "en": "Blood-Moon Hwatu Kingdom", "emoji": "🎴", "risk": 2},
    {"id": "reverse_casino", "ko": "역행 카지노", "en": "Reverse-Time Casino", "emoji": "🎰", "risk": 3},
    {"id": "horse_world", "ko": "역전 경마세계", "en": "Inverted Racing World", "emoji": "🏇", "risk": 2},
    {"id": "silent_city", "ko": "NPC가 사라진 폐쇄도시", "en": "Silent City Without NPCs", "emoji": "🏙️", "risk": 4},
    {"id": "ghost_train", "ko": "무한 유령열차", "en": "Endless Ghost Train", "emoji": "🚆", "risk": 3},
    {"id": "wild_companions", "ko": "거대 동료의 야생행성", "en": "Wild Planet of Giant Companions", "emoji": "🐾", "risk": 2},
    {"id": "abaddon_core", "ko": "아바돈 핵심차원", "en": "ABADDON Core Dimension", "emoji": "🌑", "risk": 5},
)

FX_PROFILES: Dict[str, Dict[str, Any]] = {
    "도시채집": {"en": "citygather", "kind": "gather", "ko": ["⛏️ 광맥 탐색", "🪨 곡괭이가 암반을 때립니다", "💥 균열 확장", "✨ 자원 신호 확인"], "en_lines": ["⛏️ Scanning the vein", "🪨 Pickaxe strikes the rock", "💥 Fracture expanding", "✨ Resource signal acquired"]},
    "도시제작": {"en": "citycraft", "kind": "craft", "ko": ["🔨 제작대 가동", "🔥 용광로 점화", "⚙️ 재료 정밀 가공", "✨ 품질 판정"], "en_lines": ["🔨 Workbench online", "🔥 Forge ignited", "⚙️ Precision processing", "✨ Quality check"]},
    "월드보스공격": {"en": "worldbossattack", "kind": "boss", "ko": ["👹 보스 신호 포착", "⚔️ 공격 준비", "💥 충돌 발생", "🔥 반격 경계"], "en_lines": ["👹 Boss signal locked", "⚔️ Preparing assault", "💥 Impact confirmed", "🔥 Watching the counterattack"]},
    "협동보스공격": {"en": "attackcoopboss", "kind": "boss", "ko": ["🛡️ 공격대 동기화", "⚔️ 약점 조준", "💥 합동 타격", "📊 피해 집계"], "en_lines": ["🛡️ Raid synchronized", "⚔️ Targeting weakness", "💥 Combined strike", "📊 Calculating damage"]},
    "보스공격": {"en": "bossattack", "kind": "boss", "ko": ["🌑 차원 보스 각성", "⚔️ 크루 전진", "⚡ 약점 폭발", "👑 결과 판정"], "en_lines": ["🌑 Rift boss awakened", "⚔️ Crew advancing", "⚡ Weak point detonated", "👑 Resolving outcome"]},
    "탐험선택": {"en": "expeditionchoice", "kind": "explore", "ko": ["🧭 경로 계산", "👣 폐허 진입", "🌌 이상 신호 감지", "🗝️ 결과 해석"], "en_lines": ["🧭 Plotting route", "👣 Entering the ruins", "🌌 Anomaly detected", "🗝️ Resolving the choice"]},
    "차원탐사": {"en": "dimensionexplore", "kind": "explore", "ko": ["🌀 차원문 안정화", "🚀 관측선 진입", "🌌 미지의 좌표 해독", "📡 귀환 신호 확보"], "en_lines": ["🌀 Stabilizing the gate", "🚀 Probe entering", "🌌 Decoding unknown coordinates", "📡 Return signal secured"]},
    "건설기부": {"en": "donateconstruction", "kind": "build", "ko": ["🏗️ 건설 구역 확보", "🧱 자재 반입", "⚙️ 구조물 조립", "✨ 공정 갱신"], "en_lines": ["🏗️ Securing construction zone", "🧱 Materials delivered", "⚙️ Structure assembly", "✨ Progress updated"]},
    "거래구매": {"en": "citymarketbuy", "kind": "trade", "ko": ["🪙 에스크로 확인", "🤝 거래 서명", "📦 물품 이전", "✅ 장부 기록"], "en_lines": ["🪙 Checking escrow", "🤝 Signing trade", "📦 Transferring item", "✅ Ledger updated"]},
    "동료탐험": {"en": "companionexplore", "kind": "explore", "ko": ["🐾 동료 출발", "🧭 흔적 추적", "✨ 발견물 확인", "🏠 귀환 준비"], "en_lines": ["🐾 Companion departed", "🧭 Tracking traces", "✨ Inspecting discovery", "🏠 Preparing return"]},
}


def _font(size: int, bold: bool = True) -> ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _font_status() -> Dict[str, Any]:
    for path in FONT_CANDIDATES:
        try:
            f = ImageFont.truetype(path, size=24)
            bbox = f.getbbox("한글 ABADDON")
            if bbox and bbox[2] > bbox[0]:
                return {"loaded": True, "path": path, "name": Path(path).name}
        except Exception:
            pass
    return {"loaded": False, "path": "", "name": "PIL default"}


def _root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault(DATA_KEY, {})
    root.setdefault("schema", 1)
    root.setdefault("guilds", {})
    root.setdefault("global_lineage", [])
    root.setdefault("federations", {})
    root.setdefault("exchange", {})
    return root


def _guild(root: MutableMapping[str, Any], guild_id: int, guild_name: str = "") -> MutableMapping[str, Any]:
    row = root["guilds"].setdefault(str(int(guild_id or 0)), {})
    defaults = {
        "settings": {"effects": "cinematic", "city_theme": "neon_night", "conversation": "contextual", "public": False, "network_opt_in": False, "content_share": False},
        "decorations": [
            {"id": "neon_gate", "x": 88, "y": 610, "scale": 0.42},
            {"id": "fountain", "x": 590, "y": 585, "scale": 0.40},
            {"id": "street_lamp", "x": 1040, "y": 610, "scale": 0.36},
            {"id": "airship", "x": 1030, "y": 105, "scale": 0.36},
        ],
        "decor_backups": [], "decor_history": [], "dimensions": {"active": None, "discovered": [], "history": []},
        "campaign": {"active": False, "chapter": 0, "members": [], "choices": [], "ending": None},
        "ship": {"name": "ABYSS-01", "level": 1, "xp": 0, "facilities": {"차원엔진": 1, "관측실": 1, "제작공방": 0, "유물보관고": 0}},
        "crews": {}, "raid": None, "studio": {"drafts": {}, "published": {}}, "lineage": [], "replays": [],
        "stats": {"fx_started": 0, "maps_rendered": 0, "chat_turns": 0},
    }
    for k, v in defaults.items():
        if k not in row:
            row[k] = deepcopy(v)
    for k, v in defaults["settings"].items(): row["settings"].setdefault(k, v)
    return row


def _locale(bot: commands.Bot, ctx: commands.Context) -> str:
    try: return _ctx_locale(bot, ctx)
    except Exception: return "ko"


def _text(loc: str, ko: str, en: str) -> str:
    return en if loc == "en" else ko


def _safe_component_path(component_id: str) -> Optional[Path]:
    if component_id not in COMPONENT_LABELS: return None
    path = ASSET_ROOT / "city" / "components" / f"{component_id}.png"
    return path if path.exists() else None


def _fit_text(draw: ImageDraw.ImageDraw, text: str, box: Tuple[int, int, int, int], max_size: int, fill: Tuple[int, int, int], *, anchor: str = "mm") -> None:
    x1, y1, x2, y2 = box
    size = max_size
    while size > 12:
        f = _font(size)
        b = draw.textbbox((0, 0), text, font=f)
        if b[2] - b[0] <= x2 - x1 - 12 and b[3] - b[1] <= y2 - y1 - 8:
            draw.text(((x1+x2)//2, (y1+y2)//2), text, font=f, fill=fill, anchor=anchor)
            return
        size -= 2
    draw.text(((x1+x2)//2, (y1+y2)//2), text[:18], font=_font(12), fill=fill, anchor=anchor)


def _paste_scaled(base: Image.Image, path: Path, x: int, y: int, scale: float, rotation: int = 0) -> None:
    try:
        im = Image.open(path).convert("RGBA")
        size = max(40, int(256 * float(scale)))
        im = im.resize((size, size), Image.Resampling.LANCZOS)
        if int(rotation) % 360:
            im = im.rotate(-int(rotation) % 360, resample=Image.Resampling.BICUBIC, expand=True)
        base.alpha_composite(im, (int(x), int(y)))
    except Exception:
        pass


def render_city_map(city: Mapping[str, Any], neon: Mapping[str, Any], *, locale: str = "ko", clean: bool = False) -> io.BytesIO:
    bg_path = ASSET_ROOT / "city" / "neon_city_background.png"
    if bg_path.exists():
        bg = Image.open(bg_path).convert("RGBA").resize((1400, 900), Image.Resampling.LANCZOS)
        bg = ImageEnhance.Brightness(bg).enhance(0.68)
    else:
        bg = Image.new("RGBA", (1400, 900), (7, 9, 24, 255))
    overlay = Image.new("RGBA", bg.size, (0, 0, 0, 0)); od = ImageDraw.Draw(overlay)
    od.rectangle((0, 0, 1400, 900), fill=(5, 7, 20, 85))
    od.rounded_rectangle((30, 24, 1370, 150), 24, fill=(7, 9, 26, 225), outline=(152, 88, 255, 230), width=4)
    bg.alpha_composite(overlay)
    draw = ImageDraw.Draw(bg)
    title = str(city.get("name", "BLACK CITY"))
    trait = str(city.get("trait", "NEON ABYSS"))
    _fit_text(draw, title, (55, 34, 810, 94), 44, (248, 242, 255))
    draw.text((62, 112), trait if locale == "ko" else "Living City · Infinite Dimensions", font=_font(22), fill=(197, 164, 255))
    metrics = city.get("metrics", {})
    metric_specs = [("번영","Prosperity","prosperity","🌆"),("경제","Economy","economy","🪙"),("치안","Security","security","🛡️"),("혼돈","Chaos","chaos","🌑"),("명성","Fame","fame","👑")]
    mx = 815
    for ko,en,key,emoji in metric_specs:
        value=max(0,min(100,int(metrics.get(key,0))))
        draw.text((mx,48),f"{emoji} {ko if locale=='ko' else en}",font=_font(16),fill=(225,218,242))
        draw.rounded_rectangle((mx,78,mx+98,96),8,fill=(35,36,57))
        draw.rounded_rectangle((mx,78,mx+int(98*value/100),96),8,fill=(142,77,226))
        draw.text((mx+49,120),str(value),font=_font(15),fill='white',anchor='mm')
        mx += 108

    # district cards, guaranteed CJK font
    positions=[(55,185),(315,170),(575,185),(835,170),(1095,185),(165,410),(485,410),(805,410),(1120,410)]
    for (district,state),(x,y) in zip(city.get("districts",{}).items(),positions):
        unlocked=bool(state.get("unlocked",False)); owner=str(state.get("owner") or "")
        card=Image.new("RGBA",(230,190),(13,15,35,225)); cd=ImageDraw.Draw(card)
        cd.rounded_rectangle((3,3,227,187),22,fill=(17,21,47,235) if unlocked else (22,22,30,225),outline=(160,91,244) if unlocked else (77,77,92),width=4)
        comp=DISTRICT_COMPONENTS.get(district)
        p=_safe_component_path(comp or "")
        if p:
            icon=Image.open(p).convert('RGBA').resize((112,112),Image.Resampling.LANCZOS)
            card.alpha_composite(icon,(59,8))
        label=district if locale=='ko' else str(DISTRICTS.get(district,{}).get('en',district))
        _fit_text(cd,label,(10,118,220,149),21,(250,248,255) if unlocked else (145,145,155))
        sub=(f"🏴 {owner}" if owner else ("중립" if locale=='ko' else "Neutral")) if unlocked else ("🔒 잠김" if locale=='ko' else "🔒 Locked")
        _fit_text(cd,sub,(10,150,220,181),15,(190,185,210))
        bg.alpha_composite(card,(x,y))

    for decor in sorted(neon.get("decorations",[])[:40], key=lambda d: int(d.get("layer", 0) or 0)):
        p=_safe_component_path(str(decor.get("id","")))
        if p: _paste_scaled(bg,p,int(decor.get("x",0)),int(decor.get("y",0)),float(decor.get("scale",0.35)),int(decor.get("rotation",0) or 0))

    if not clean:
        panel=Image.new("RGBA",(1330,140),(7,9,24,225)); pd=ImageDraw.Draw(panel)
        pd.rounded_rectangle((2,2,1328,138),20,fill=(9,12,31,235),outline=(107,74,180),width=3)
        pd.text((24,24),"✨ "+("도시 장식" if locale=='ko' else "City Decorations"),font=_font(23),fill=(236,220,255))
        names=[]
        for d in neon.get("decorations",[])[:12]:
            ko,en=COMPONENT_LABELS.get(str(d.get('id')), (str(d.get('id')),str(d.get('id'))))
            names.append(ko if locale=='ko' else en)
        pd.text((24,62)," · ".join(names) or ("장식 없음" if locale=='ko' else "No decorations"),font=_font(18),fill=(200,199,220))
        pd.text((24,103),("!도시꾸미기 · !도시부품 · !도시사진" if locale=='ko' else "!citydecorate · !cityparts · !cityphoto"),font=_font(17),fill=(139,201,255))
        bg.alpha_composite(panel,(35,735))

    out=io.BytesIO(); bg.convert('RGB').save(out,format='PNG',quality=94,optimize=True); out.seek(0); return out


class DecorSelect(discord.ui.Select):
    def __init__(self, view: "DecorView"):
        self.owner_view = view
        options = []
        for cid, (ko, en) in COMPONENT_LABELS.items():
            options.append(
                discord.SelectOption(
                    label=ko if view.locale == "ko" else en,
                    value=cid,
                    description=_text(view.locale, f"{cid} · 도시 지도에 바로 배치", f"{cid} · place directly on the city map"),
                )
            )
        super().__init__(placeholder=_text(view.locale, "도시 부품 선택", "Choose a city part"), options=options[:25], row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.owner_view
        previous = view.selected
        view.selected = self.values[0]
        ko, en = COMPONENT_LABELS[view.selected]
        old_ko, old_en = COMPONENT_LABELS.get(previous, (previous, previous))
        view.last_action = _text(
            view.locale,
            f"부품 선택 변경 · {old_ko} → {ko}",
            f"Part selection changed · {old_en} → {en}",
        )
        view.action_count += 1
        view.rebuild()
        path = _safe_component_path(view.selected)
        await interaction.response.defer()
        kwargs = {"embed": view.embed(), "view": view}
        if path:
            kwargs["attachments"] = [discord.File(path, filename=path.name)]
        try:
            await interaction.edit_original_response(**kwargs)
        except (TypeError, discord.HTTPException):
            kwargs.pop("attachments", None)
            await interaction.edit_original_response(**kwargs)


class DecorView(discord.ui.View):
    def __init__(
        self,
        *,
        owner_id: int,
        locale: str,
        row: MutableMapping[str, Any],
        city: MutableMapping[str, Any],
        save_data: Callable[[], None],
    ):
        super().__init__(timeout=600)
        self.owner_id = int(owner_id)
        self.locale = locale
        self.row = row
        self.city = city
        self.save_data = save_data
        self.selected = "neon_gate"
        self.x = 530
        self.y = 570
        self.scale = 0.38
        self.rotation = 0
        self.layer = 0
        self.last_action = _text(locale, "공방을 열었습니다. 배치할 부품을 선택하세요.", "Workshop opened. Choose a part to place.")
        self.action_count = 0
        self.rebuild()

    def rebuild(self) -> None:
        self.clear_items()
        self.add_item(DecorSelect(self))
        for label, dx, dy, action_ko, action_en in (
            ("⬅️", -40, 0, "왼쪽 이동", "Move left"),
            ("➡️", 40, 0, "오른쪽 이동", "Move right"),
            ("⬆️", 0, -40, "위로 이동", "Move up"),
            ("⬇️", 0, 40, "아래로 이동", "Move down"),
        ):
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, row=1)

            async def move_callback(interaction: discord.Interaction, dx=dx, dy=dy, action_ko=action_ko, action_en=action_en):
                self.x = max(0, min(1200, self.x + dx))
                self.y = max(150, min(700, self.y + dy))
                ko, en = COMPONENT_LABELS[self.selected]
                self.last_action = _text(
                    self.locale,
                    f"{ko} {action_ko} · X {self.x} / Y {self.y}",
                    f"{en} · {action_en} · X {self.x} / Y {self.y}",
                )
                self.action_count += 1
                await interaction.response.edit_message(embed=self.embed(), view=self)

            button.callback = move_callback
            self.add_item(button)

        apply_button = discord.ui.Button(label=_text(self.locale, "✨ 적용", "✨ Apply"), style=discord.ButtonStyle.success, row=2)
        undo_button = discord.ui.Button(label=_text(self.locale, "↩️ 최근 복구", "↩️ Undo"), style=discord.ButtonStyle.danger, row=2)
        smaller_button = discord.ui.Button(label=_text(self.locale, "➖ 축소", "➖ Smaller"), style=discord.ButtonStyle.secondary, row=2)
        larger_button = discord.ui.Button(label=_text(self.locale, "➕ 확대", "➕ Larger"), style=discord.ButtonStyle.secondary, row=2)
        preview_button = discord.ui.Button(label=_text(self.locale, "🏙️ 도시 미리보기", "🏙️ City Preview"), style=discord.ButtonStyle.primary, row=2)

        async def apply_callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            ko, en = COMPONENT_LABELS[self.selected]
            before_count = len(self.row.get("decorations", []))
            self.row.setdefault("decor_backups", []).append(deepcopy(self.row.get("decorations", [])))
            self.row["decor_backups"] = self.row["decor_backups"][-10:]
            placed = {
                "id": self.selected,
                "label": ko,
                "x": self.x,
                "y": self.y,
                "scale": round(self.scale, 3),
                "rotation": int(self.rotation),
                "layer": int(self.layer),
                "created_by": int(interaction.user.id),
                "created_at": int(time.time()),
                "action": "place",
            }
            self.row.setdefault("decorations", []).append(placed)
            self.row["decorations"] = self.row["decorations"][-40:]
            history = self.row.setdefault("decor_history", [])
            history.append({
                "at": int(time.time()),
                "by": int(interaction.user.id),
                "action": "place",
                "part": self.selected,
                "label": ko,
                "x": self.x,
                "y": self.y,
                "scale": round(self.scale, 3),
                "rotation": int(self.rotation),
                "layer": int(self.layer),
                "before": before_count,
                "after": len(self.row["decorations"]),
            })
            self.row["decor_history"] = history[-100:]
            self.last_action = _text(
                self.locale,
                f"배치 완료 · {ko} 1개 추가 · 총 {len(self.row['decorations'])}개",
                f"Placed · {en} added · {len(self.row['decorations'])} total",
            )
            self.action_count += 1
            self.save_data()
            path = _safe_component_path(self.selected)
            edit_kwargs = {"embed": self.embed(), "view": self}
            if path:
                edit_kwargs["attachments"] = [discord.File(path, filename=path.name)]
            try:
                await interaction.edit_original_response(**edit_kwargs)
            except (TypeError, discord.HTTPException):
                edit_kwargs.pop("attachments", None)
                await interaction.edit_original_response(**edit_kwargs)
            result = discord.Embed(
                title=_text(self.locale, "✅ 도시 장식 배치 완료", "✅ City Decoration Placed"),
                description=_text(
                    self.locale,
                    f"**한 행동:** 공방에서 `{ko}` 배치\n**추가된 부품:** `{self.selected}` · {ko}",
                    f"**Action:** placed `{en}` in the workshop\n**Added part:** `{self.selected}` · {en}",
                ),
                color=0x2ECC71,
            )
            result.add_field(name=_text(self.locale, "배치 위치", "Position"), value=f"X `{self.x}` · Y `{self.y}` · Scale `{self.scale:.2f}` · Rotate `{self.rotation}°` · Layer `{self.layer}`", inline=False)
            result.add_field(name=_text(self.locale, "도시 장식 수", "Decoration Count"), value=f"`{before_count}` → **{len(self.row['decorations'])}**", inline=True)
            result.add_field(name=_text(self.locale, "기록", "History"), value=_text(self.locale, "도시 장식 작업 기록에 저장됨", "Saved to city decoration history"), inline=True)
            await interaction.followup.send(embed=result, ephemeral=True)

        async def undo_callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            backups = self.row.setdefault("decor_backups", [])
            if not backups:
                await interaction.followup.send(_text(self.locale, "복구할 장식 백업이 없습니다.", "No decoration backup is available."), ephemeral=True)
                return
            before = len(self.row.get("decorations", []))
            self.row["decorations"] = backups.pop()
            after = len(self.row.get("decorations", []))
            self.row.setdefault("decor_history", []).append({"at": int(time.time()), "by": int(interaction.user.id), "action": "undo", "before": before, "after": after})
            self.row["decor_history"] = self.row["decor_history"][-100:]
            self.last_action = _text(self.locale, f"최근 장식 상태 복구 · {before}개 → {after}개", f"Restored decoration backup · {before} → {after}")
            self.action_count += 1
            self.save_data()
            await interaction.edit_original_response(embed=self.embed(), view=self)
            await interaction.followup.send(_text(self.locale, f"↩️ 최근 장식 상태로 복구했습니다. 현재 {after}개입니다.", f"↩️ Restored the latest decoration backup. {after} parts remain."), ephemeral=True)

        async def resize_callback(interaction: discord.Interaction, delta: float) -> None:
            self.scale = max(0.18, min(0.80, round(self.scale + delta, 2)))
            ko, en = COMPONENT_LABELS[self.selected]
            self.last_action = _text(self.locale, f"{ko} 크기 조정 · Scale {self.scale:.2f}", f"{en} resized · Scale {self.scale:.2f}")
            self.action_count += 1
            await interaction.response.edit_message(embed=self.embed(), view=self)

        async def smaller_callback(interaction: discord.Interaction):
            await resize_callback(interaction, -0.05)

        async def larger_callback(interaction: discord.Interaction):
            await resize_callback(interaction, 0.05)

        async def preview_callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True, thinking=True)
            preview = render_city_map(self.city, self.row, locale=self.locale, clean=True)
            await interaction.followup.send(
                _text(self.locale, "🏙️ 현재 저장된 장식 기준 도시 미리보기입니다.", "🏙️ City preview using the currently saved decorations."),
                file=discord.File(preview, filename="ABADDON_CITY_WORKSHOP_PREVIEW.png"),
                ephemeral=True,
            )

        apply_button.callback = apply_callback
        undo_button.callback = undo_callback
        smaller_button.callback = smaller_callback
        larger_button.callback = larger_callback
        preview_button.callback = preview_callback
        for item in (apply_button, undo_button, smaller_button, larger_button, preview_button):
            self.add_item(item)

        rotate_button = discord.ui.Button(label=_text(self.locale, "🔄 회전", "🔄 Rotate"), style=discord.ButtonStyle.secondary, row=3)
        layer_down = discord.ui.Button(label=_text(self.locale, "⬇ 뒤로", "⬇ Layer Down"), style=discord.ButtonStyle.secondary, row=3)
        layer_up = discord.ui.Button(label=_text(self.locale, "⬆ 앞으로", "⬆ Layer Up"), style=discord.ButtonStyle.secondary, row=3)
        remove_last = discord.ui.Button(label=_text(self.locale, "🗑 최근 삭제", "🗑 Remove Last"), style=discord.ButtonStyle.danger, row=3)
        history_button = discord.ui.Button(label=_text(self.locale, "📜 작업 기록", "📜 History"), style=discord.ButtonStyle.primary, row=3)

        async def rotate_callback(interaction: discord.Interaction) -> None:
            self.rotation = (self.rotation + 45) % 360
            ko, en = COMPONENT_LABELS[self.selected]
            self.last_action = _text(self.locale, f"{ko} 회전 · {self.rotation}°", f"{en} rotated · {self.rotation}°")
            await interaction.response.edit_message(embed=self.embed(), view=self)

        async def layer_callback(interaction: discord.Interaction, delta: int) -> None:
            self.layer = max(-10, min(10, self.layer + delta))
            self.last_action = _text(self.locale, f"배치 레이어 조정 · {self.layer}", f"Placement layer changed · {self.layer}")
            await interaction.response.edit_message(embed=self.embed(), view=self)

        async def remove_callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            decorations = self.row.setdefault("decorations", [])
            if not decorations:
                await interaction.followup.send(_text(self.locale, "삭제할 도시 부품이 없습니다.", "There is no city part to remove."), ephemeral=True)
                return
            self.row.setdefault("decor_backups", []).append(deepcopy(decorations))
            removed = decorations.pop()
            self.row.setdefault("decor_history", []).append({"at": int(time.time()), "by": int(interaction.user.id), "action": "remove", "part": removed.get("id"), "before": len(decorations)+1, "after": len(decorations)})
            self.row["decor_history"] = self.row["decor_history"][-100:]
            self.save_data()
            ko, en = COMPONENT_LABELS.get(str(removed.get("id")), (str(removed.get("id")), str(removed.get("id"))))
            self.last_action = _text(self.locale, f"최근 부품 삭제 · {ko} · 현재 {len(decorations)}개", f"Removed last part · {en} · {len(decorations)} remain")
            await interaction.edit_original_response(embed=self.embed(), view=self)
            await interaction.followup.send(_text(self.locale, f"🗑 `{ko}`를 도시에서 제거했습니다.", f"🗑 Removed `{en}` from the city."), ephemeral=True)

        async def history_callback(interaction: discord.Interaction) -> None:
            rows = list(self.row.get("decor_history", []))[-10:]
            lines = []
            for item in reversed(rows):
                part = str(item.get("part", "-")); ko, en = COMPONENT_LABELS.get(part, (part, part))
                action = str(item.get("action", "update"))
                lines.append(f"• {action} · {ko if self.locale == 'ko' else en} · {item.get('before','?')}→{item.get('after','?')}")
            await interaction.response.send_message("\n".join(lines) or _text(self.locale, "작업 기록이 없습니다.", "No workshop history."), ephemeral=True)

        rotate_button.callback = rotate_callback
        layer_down.callback = lambda interaction: layer_callback(interaction, -1)
        layer_up.callback = lambda interaction: layer_callback(interaction, 1)
        remove_last.callback = remove_callback
        history_button.callback = history_callback
        for item in (rotate_button, layer_down, layer_up, remove_last, history_button):
            self.add_item(item)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.owner_id:
            return True
        await interaction.response.send_message(_text(self.locale, "이 꾸미기 화면은 실행자만 사용할 수 있습니다.", "Only the user who opened this decorator can use it."), ephemeral=True)
        return False

    def embed(self) -> discord.Embed:
        ko, en = COMPONENT_LABELS[self.selected]
        decorations = self.row.get("decorations", [])
        history = self.row.get("decor_history", [])
        e = discord.Embed(
            title=_text(self.locale, "🎨 도시 꾸미기 공방", "🎨 City Decoration Workshop"),
            description=_text(
                self.locale,
                "부품 선택 → 위치/크기 조정 → 적용 순서로 사용합니다. 모든 적용·복구 행동은 작업 기록에 남습니다.",
                "Choose a part → adjust position/size → apply. Every placement and undo is recorded.",
            ),
            color=0x8E44AD,
        )
        e.add_field(name=_text(self.locale, "선택 부품", "Selected Part"), value=(ko if self.locale == "ko" else en) + f" (`{self.selected}`)", inline=False)
        e.add_field(name=_text(self.locale, "배치 좌표", "Position"), value=f"X `{self.x}` · Y `{self.y}` · Scale `{self.scale:.2f}` · Rotate `{self.rotation}°` · Layer `{self.layer}`", inline=False)
        e.add_field(name=_text(self.locale, "방금 한 행동", "Latest Action"), value=self.last_action[:1024], inline=False)
        e.add_field(name=_text(self.locale, "적용 시 추가", "On Apply"), value=_text(self.locale, f"{ko} 1개가 도시 레이어에 추가됩니다.", f"One {en} will be added to the city layer."), inline=True)
        e.add_field(name=_text(self.locale, "현재 저장", "Saved"), value=f"장식 **{len(decorations)}/40** · 기록 **{len(history)}/100**", inline=True)
        path = _safe_component_path(self.selected)
        if path:
            e.set_thumbnail(url=f"attachment://{path.name}")
        e.set_footer(text=_text(self.locale, "선택을 바꾸면 첨부 이미지도 즉시 교체됩니다.", "Changing the selection also replaces the attached preview image."))
        return e


def _detect_english(text: str, session: Optional[MutableMapping[str,Any]]) -> bool:
    if session and session.get('locale') in {'ko','en'}: return session.get('locale')=='en'
    ko=len(re.findall(r'[가-힣ㄱ-ㅎㅏ-ㅣ]',text)); en=len(re.findall(r'[A-Za-z]',text))
    return en>ko*1.4 and en>=3


def _extract_topic(text: str, english: bool) -> str:
    stop_en={'what','why','how','the','this','that','with','about','your','you','are','can','could','would','please','tell','me','and','but','then'}
    stop_ko={'뭐','무엇','왜','어떻게','그거','그건','나는','내가','너는','아바돈','그리고','근데','그런데','좀','정말','진짜'}
    tokens=re.findall(r"[A-Za-z]{3,}|[가-힣]{2,}",text)
    tokens=[t for t in tokens if t.casefold() not in stop_en and t not in stop_ko]
    return tokens[-1] if tokens else ''


def _conversation_reply(state: MutableMapping[str,Any], user: Any, text: str, session: Optional[MutableMapping[str,Any]]) -> Optional[Tuple[str,Tuple[str,...],str]]:
    mode = str(state.get('settings', {}).get('v1500_mode', 'contextual'))
    if mode == 'classic':
        return None
    english=_detect_english(text,session); loc='en' if english else 'ko'
    if session is not None: session['locale']=loc
    norm=' '.join(str(text).strip().split()); low=norm.casefold(); name=str(getattr(user,'display_name',getattr(user,'name','')) or '')[:24]
    topic=_extract_topic(norm,english)
    prev_user=str((session or {}).get('last_user_text','')); prev_bot=str((session or {}).get('last_bot_text','')); prev_topic=str((session or {}).get('topic',''))
    if topic and session is not None: session['topic']=topic
    topic=topic or prev_topic
    history=list((session or {}).get('history',[]))

    if english:
        if any(x in low for x in ('what did i say','what were we talking','continue from before','remember what i said')):
            answer=f"We were talking about **{topic or 'your last message'}**. Your previous message was: “{prev_user[:180]}”. I can continue from there—what part should we dig into next?"
        elif low in {'yes','yeah','yep','okay','ok','sure','right'}:
            answer=f"Got it. Let’s keep going with **{topic or 'that'}**. Which matters more right now: the result, the process, or how it feels?"
        elif low in {'no','nope','not that','that is not it'}:
            answer="Understood—I took the conversation in the wrong direction. Give me the outcome you want in one sentence, and I’ll reset around that."
        elif any(q in low for q in ('why do you think','why is that','why?')) and prev_bot:
            answer=f"Because I was following the context in your previous message and prioritizing a reversible, low-risk next step. My last answer was about: “{prev_bot[:150]}”. Which assumption should I change?"
        elif '?' in norm or low.startswith(('what ','how ','why ','can ','could ','would ','is ','are ')):
            answer=f"Here’s how I understand your question about **{topic or 'this'}**: you want a useful answer that fits what we were already discussing, not a generic reply. Based on the current context, I’d start by clarifying the exact outcome, then choose the smallest testable next action. What result would count as ‘done’ for you?"
        elif any(x in low for x in ('i am tired','im tired','exhausted','burned out')):
            answer=f"That sounds draining, {name}. We do not have to solve everything in one turn. What is the one thing you want off your mind first?"
        elif any(x in low for x in ('thank','thanks','appreciate')):
            answer="You’re welcome. I’m keeping the thread of the conversation, so you can continue without restating everything. What should we tackle next?"
        elif any(x in low for x in ('hello','hi ','hey','good morning','good evening')):
            answer=f"Hey {name}. I’m here, and I’ll keep track of this conversation as we go. What’s on your mind?"
        else:
            bridge=f" We were previously on **{prev_topic}**." if prev_topic else ''
            answer=f"I’m following you.{bridge} The part that stands out in what you said is **{topic or 'the direction you want'}**. Tell me one more detail and I’ll respond to that rather than resetting the conversation."
        return answer,('💬','🖤','✨'),'v1500_en'

    if any(x in norm for x in ('내가 뭐라고 했','아까 무슨 얘기','전에 말한 거','기억해','대화 이어')):
        answer=f"우리는 **{topic or '방금 이야기'}**를 이어가고 있었어요. 이전 메시지는 “{prev_user[:180]}”였고요. 그중 어느 부분부터 다시 잡을까요?"
    elif norm in {'응','응응','그래','좋아','맞아','ㅇㅇ','알겠어','오케이'}:
        answer=f"좋아요. 그럼 **{topic or '그 이야기'}**를 그대로 이어가죠. 지금 더 중요한 건 결과, 과정, 아니면 마음에 걸리는 부분 중 어느 쪽이에요?"
    elif norm in {'아니','아냐','그건 아니야','ㄴㄴ','싫어'}:
        answer="알겠어요. 제가 방향을 잘못 잡았네요. 원하는 결과를 한 문장으로 말해 주면 그 기준으로 다시 맞출게요."
    elif any(x in norm for x in ('왜 그렇게 생각','왜 그래','왜?')) and prev_bot:
        answer=f"앞선 문맥에서 되돌릴 수 있고 위험이 적은 선택을 우선했기 때문이에요. 제가 방금 말한 핵심은 “{prev_bot[:150]}”였어요. 여기서 제가 잘못 가정한 부분이 뭘까요?"
    elif '?' in norm or norm.endswith(('까','나요','니','어')) and any(x in norm for x in ('뭐','무엇','어떻게','왜','가능','할 수','알려')):
        answer=f"질문의 핵심을 **{topic or '현재 상황'}**으로 이해했어요. 뻔한 답보다 지금 대화에 맞는 답을 원한다는 것도요. 먼저 원하는 결과를 정확히 잡고, 그다음 가장 작게 시험할 행동을 고르는 게 좋아요. 어떤 상태가 되면 ‘해결됐다’고 느낄까요?"
    elif any(x in norm for x in ('피곤','지쳤','힘들어','번아웃')):
        answer=f"많이 소모된 것 같아요, {name}. 전부 해결하려 하지 말고 지금 머릿속에서 가장 먼저 내려놓고 싶은 것 하나만 말해 줘요. 거기부터 같이 정리해요."
    elif any(x in norm for x in ('고마워','감사','땡큐')):
        answer="별말씀을요. 지금 대화 흐름은 계속 기억하고 있으니 처음부터 다시 설명하지 않아도 돼요. 다음으로 뭘 같이 볼까요?"
    elif any(x in norm for x in ('안녕','좋은 아침','좋은 저녁','하이')):
        answer=f"반가워요, {name}. 이번에는 말을 끊어서 답하지 않고 흐름을 따라갈게요. 오늘은 무슨 얘기부터 할까요?"
    else:
        bridge=f" 앞에서는 **{prev_topic}** 이야기를 했고요." if prev_topic else ''
        answer=f"응, 따라가고 있어요.{bridge} 이번 말에서 가장 눈에 들어오는 건 **{topic or '원하는 방향'}**이에요. 한 가지만 더 구체적으로 말해 주면 대화를 초기화하지 않고 바로 이어서 답할게요."
    return answer,('💬','🖤','✨'),'v1500_ko'


def register_v1500_neon_abyss(
    bot: commands.Bot,
    get_user: Callable[[int], Optional[MutableMapping[str, Any]]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[Any, Any],
    guide: List[Dict[str, Any]],
) -> None:
    if getattr(bot,"_abaddon_v1500_registered",False): return
    bot._abaddon_v1500_registered=True
    root=_root(world_data); black_root=ensure_black_city_root(world_data); font_status=_font_status(); active_fx:Dict[int,Dict[str,Any]]={}

    def row(ctx:commands.Context)->MutableMapping[str,Any]:
        g=ctx.guild; return _guild(root,int(getattr(g,'id',0) or 0),str(getattr(g,'name','ABADDON')))
    def black_city(ctx:commands.Context)->MutableMapping[str,Any]:
        g=ctx.guild; return ensure_black_city_guild(black_root,int(getattr(g,'id',0) or 0),guild_name=str(getattr(g,'name','ABADDON')))
    def loc(ctx:commands.Context)->str:return _locale(bot,ctx)
    async def registered(ctx:commands.Context)->Optional[MutableMapping[str,Any]]:
        if not await check_registered(ctx): return None
        return get_user(int(ctx.author.id))

    # Replace the old flat city map with the layered renderer while keeping access names.
    old=bot.get_command('도시지도')
    old_aliases=list(getattr(old,'aliases',[]) or []) if old else ['citymap','blackcitymap']
    if old: bot.remove_command('도시지도')

    @bot.command(name='도시지도',aliases=list(dict.fromkeys(old_aliases+['neoncitymap'])),help='한글 안전 글꼴과 장식 레이어를 사용하는 NEON ABYSS 도시 지도를 표시합니다.')
    async def city_map_v1500(ctx:commands.Context)->None:
        n=row(ctx); c=black_city(ctx); n['stats']['maps_rendered']=int(n['stats'].get('maps_rendered',0))+1; save_data()
        file=discord.File(render_city_map(c,n,locale=loc(ctx)),filename='ABADDON_v15_NEON_CITY_MAP.png')
        await ctx.send(file=file)

    @bot.command(name='도시전경',aliases=['citypanorama','neonpanorama'],help='정보 패널을 줄인 꾸민 도시 전경을 표시합니다.')
    async def city_panorama(ctx:commands.Context)->None:
        await ctx.send(file=discord.File(render_city_map(black_city(ctx),row(ctx),locale=loc(ctx),clean=True),filename='ABADDON_v15_CITY_PANORAMA.png'))

    @bot.command(name='도시사진',aliases=['cityphoto','citysnapshot'],help='현재 도시 상태와 장식을 기념 사진으로 저장합니다.')
    async def city_photo(ctx:commands.Context)->None:
        n=row(ctx); data=render_city_map(black_city(ctx),n,locale=loc(ctx),clean=True)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S'); n.setdefault('lineage',[]).append({'type':'photo','at':int(time.time()),'by':int(ctx.author.id),'file':f'city_{stamp}.png'}); n['lineage']=n['lineage'][-100:]; save_data()
        await ctx.send(_text(loc(ctx),'📸 현재 도시 전경을 기록했습니다.','📸 Current city panorama archived.'),file=discord.File(data,filename=f'ABADDON_CITY_{stamp}.png'))

    @bot.command(name='도시부품',aliases=['cityparts','citypartcatalog'],help='꾸밀 수 있는 도시 부품 이미지 목록 또는 상세 이미지를 표시합니다.')
    async def city_parts(ctx:commands.Context,부품:str='')->None:
        l=loc(ctx); token=str(부품).strip().lower()
        if token and token in COMPONENT_LABELS:
            p=_safe_component_path(token); ko,en=COMPONENT_LABELS[token]
            if p: await ctx.send(f"**{ko if l=='ko' else en}** · `{token}`",file=discord.File(p,filename=p.name)); return
        lines=[]
        for cid,(ko,en) in COMPONENT_LABELS.items(): lines.append(f"`{cid}` · {ko if l=='ko' else en}")
        e=discord.Embed(title=_text(l,'🧩 도시 부품 20종','🧩 20 City Parts'),description='\n'.join(lines),color=0x7D3C98)
        e.set_footer(text=_text(l,'상세: !도시부품 부품ID · 배치: !도시꾸미기','Detail: !cityparts part_id · Place: !citydecorate'))
        catalog=ASSET_ROOT.parent/'v1630'/'previews'/('city_parts_catalog_ko.png' if l=='ko' else 'city_parts_catalog_en.png')
        if catalog.exists():
            catalog_name='city_parts_catalog_ko.png' if l=='ko' else 'city_parts_catalog_en.png'
            e.set_image(url=f'attachment://{catalog_name}')
            await ctx.send(embed=e,file=discord.File(catalog,filename=catalog_name))
        else:
            await ctx.send(embed=e)

    @bot.command(name='도시꾸미기',aliases=['citydecorate','decoratecity'],help='드롭다운과 방향 버튼으로 도시 부품을 배치합니다.')
    @commands.has_guild_permissions(manage_guild=True)
    async def city_decorate(ctx:commands.Context)->None:
        n=row(ctx); view=DecorView(owner_id=ctx.author.id,locale=loc(ctx),row=n,city=black_city(ctx),save_data=save_data); p=_safe_component_path(view.selected)
        await ctx.send(embed=view.embed(),view=view,file=discord.File(p,filename=p.name) if p else None)

    @bot.command(name='도시꾸미기복구',aliases=['citydecorrestore'],help='가장 최근 도시 장식 백업을 복구합니다.')
    @commands.has_guild_permissions(manage_guild=True)
    async def city_decor_restore(ctx:commands.Context)->None:
        n=row(ctx); backups=n.setdefault('decor_backups',[])
        if not backups: await ctx.send(_text(loc(ctx),'복구할 장식 백업이 없습니다.','No decoration backup is available.')); return
        n['decorations']=backups.pop(); save_data(); await ctx.send(_text(loc(ctx),'↩️ 최근 도시 장식 상태를 복구했습니다.','↩️ Restored the latest city decoration state.'))

    @bot.command(name='지역보기',aliases=['districtview','viewdistrict'],help='도시 지역의 전용 이미지를 표시합니다.')
    async def district_view(ctx:commands.Context,*,지역:str)->None:
        token=''.join(str(지역).split()); match=None
        for d in DISTRICTS:
            if token in {d,''.join(DISTRICTS[d].get('en','').lower().split())}: match=d; break
        if not match: await ctx.send(_text(loc(ctx),'지역을 찾지 못했습니다.','District not found.')); return
        cid=DISTRICT_COMPONENTS[match]; p=_safe_component_path(cid); label=match if loc(ctx)=='ko' else DISTRICTS[match]['en']
        await ctx.send(f"🏙️ **{label}**",file=discord.File(p,filename=p.name) if p else None)

    @bot.command(name='연출설정',aliases=['effectsettings','fxsettings'],help='행동 연출을 끄기·간단·화려 단계로 설정합니다.')
    @commands.has_guild_permissions(manage_guild=True)
    async def effect_settings(ctx:commands.Context,모드:str='')->None:
        l=loc(ctx); m=str(모드).lower(); maps={'끄기':'off','off':'off','간단':'compact','compact':'compact','화려':'cinematic','cinematic':'cinematic'}
        if m in maps: row(ctx)['settings']['effects']=maps[m]; save_data()
        current=row(ctx)['settings']['effects']; await ctx.send(_text(l,f"✨ 현재 연출 모드: **{current}**",f"✨ Current effect mode: **{current}**"))

    @bot.command(name='연출도감',aliases=['effectcatalog','fxpreview'],help='공격·채집·제작·탐험 이모지 연출 도감을 표시합니다.')
    async def effect_catalog(ctx:commands.Context)->None:
        p=ASSET_ROOT/'effects'/'effect_legend.png'
        await ctx.send(_text(loc(ctx),'✨ 검증된 Unicode 이모지만 사용하는 연출 도감입니다.','✨ Effect catalog using verified Unicode emoji only.'),file=discord.File(p,filename=p.name) if p.exists() else None)

    @bot.command(name='1500시각검수',aliases=['v1500visualaudit'],help='글꼴·도시 부품·연출 자산을 읽기 전용으로 검사합니다.')
    async def visual_audit(ctx:commands.Context,상세:str='')->None:
        missing=[cid for cid in COMPONENT_LABELS if _safe_component_path(cid) is None]
        checks=[('Korean font',font_status['loaded'],font_status['name']),('City components',not missing,f"{len(COMPONENT_LABELS)-len(missing)}/{len(COMPONENT_LABELS)}"),('City background',(ASSET_ROOT/'city/neon_city_background.png').exists(),'neon_city_background.png'),('Boss showcase',(ASSET_ROOT/'boss/boss_stage_showcase.png').exists(),'boss_stage_showcase.png'),('Effect legend',(ASSET_ROOT/'effects/effect_legend.png').exists(),'effect_legend.png')]
        e=discord.Embed(title='🧪 ABADDON v15.0 Visual Audit',color=0x2ECC71 if all(x[1] for x in checks) else 0xE67E22)
        e.description='\n'.join(f"{'✅' if ok else '❌'} **{name}** · {detail}" for name,ok,detail in checks)
        if missing and 상세:e.add_field(name='Missing',value=' · '.join(missing),inline=False)
        await ctx.send(embed=e)

    # Dimension voyage and campaign -------------------------------------------------
    @bot.command(name='차원문',aliases=['dimensiongate','abyssgate'],help='현재 차원 항해 상태를 확인합니다.')
    async def dimension_gate(ctx:commands.Context)->None:
        n=row(ctx); d=n['dimensions']; active=d.get('active'); l=loc(ctx)
        if not active: await ctx.send(_text(l,'🌀 차원문은 대기 중입니다. `!차원탐사`로 새 좌표를 찾으세요.','🌀 The gate is idle. Use `!dimensionexplore` to locate a new coordinate.')); return
        await ctx.send(_text(l,f"🌀 활성 차원: **{active['ko']}** · 위험 {active['risk']}/5 · 진행 {active['progress']}%",f"🌀 Active dimension: **{active['en']}** · Risk {active['risk']}/5 · Progress {active['progress']}%"))

    @bot.command(name='차원탐사',aliases=['dimensionexplore','scanrift'],help='새로운 주간 차원을 발견하거나 현재 차원을 진행합니다.')
    async def dimension_explore(ctx:commands.Context)->None:
        user=await registered(ctx)
        if user is None:return
        n=row(ctx); dims=n['dimensions']; active=dims.get('active'); l=loc(ctx)
        if not active:
            seed=(int(time.time())//604800)+int(ctx.guild.id); spec=deepcopy(DIMENSIONS[seed%len(DIMENSIONS)]); spec.update({'progress':0,'started_at':int(time.time()),'members':[int(ctx.author.id)]}); dims['active']=spec; dims['discovered']=list(dict.fromkeys(dims.get('discovered',[])+[spec['id']]))
            save_data(); await ctx.send(_text(l,f"{spec['emoji']} 새 차원 **{spec['ko']}** 발견! 위험도 {spec['risk']}/5",f"{spec['emoji']} New dimension **{spec['en']}** discovered! Risk {spec['risk']}/5")); return
        gain=random.randint(8,18); active['progress']=min(100,int(active.get('progress',0))+gain); active.setdefault('members',[]).append(int(ctx.author.id)); active['members']=list(dict.fromkeys(active['members']))
        if active['progress']>=100:
            dims.setdefault('history',[]).append({'id':active['id'],'cleared_at':int(time.time()),'members':active['members']}); n.setdefault('lineage',[]).append({'type':'dimension_clear','id':active['id'],'at':int(time.time())}); reward=5000+active['risk']*1500; user['balance']=int(user.get('balance',0))+reward; text=_text(l,f"🏆 **{active['ko']}** 완전 탐사! 보상 {reward:,}칩",f"🏆 **{active['en']}** fully explored! Reward {reward:,} chips"); dims['active']=None
        else:text=_text(l,f"🧭 탐사 진행 +{gain}% · 현재 {active['progress']}%",f"🧭 Exploration +{gain}% · Now {active['progress']}%")
        save_data(); await ctx.send(text)

    @bot.command(name='차원지도',aliases=['dimensionmap','riftmap'],help='발견한 차원과 현재 진행도를 확인합니다.')
    async def dimension_map(ctx:commands.Context)->None:
        n=row(ctx); l=loc(ctx); found=set(n['dimensions'].get('discovered',[])); lines=[]
        for d in DIMENSIONS: lines.append(f"{'✅' if d['id'] in found else '⬛'} {d['emoji']} {d['ko'] if l=='ko' else d['en']} · {'★'*d['risk']}")
        await ctx.send(embed=discord.Embed(title=_text(l,'🌌 차원 도감','🌌 Dimension Codex'),description='\n'.join(lines),color=0x6C3483))

    @bot.command(name='차원탈출',aliases=['dimensionescape','escaperift'],help='현재 차원 진행을 포기하고 안전하게 귀환합니다.')
    async def dimension_escape(ctx:commands.Context)->None:
        n=row(ctx); active=n['dimensions'].get('active')
        if not active: await ctx.send(_text(loc(ctx),'활성 차원이 없습니다.','No active dimension.')); return
        n['dimensions']['active']=None; save_data(); await ctx.send(_text(loc(ctx),'📡 차원 좌표를 폐기하고 도시로 귀환했습니다.','📡 Dimension coordinate discarded. Returned to the city.'))

    @bot.command(name='캠페인',aliases=['campaignhub','abysscampaign'],help='아바돈 게임 마스터 캠페인 상태를 확인합니다.')
    async def campaign(ctx:commands.Context)->None:
        c=row(ctx)['campaign']; l=loc(ctx)
        if not c['active']: await ctx.send(_text(l,'📖 진행 중인 캠페인이 없습니다. `!캠페인참가`로 시작하세요.','📖 No active campaign. Use `!joincampaign` to begin.')); return
        await ctx.send(_text(l,f"📖 챕터 {c['chapter']} · 참가 {len(c['members'])}명 · 선택 {len(c['choices'])}회",f"📖 Chapter {c['chapter']} · {len(c['members'])} members · {len(c['choices'])} choices"))

    @bot.command(name='캠페인참가',aliases=['joincampaign'],help='현재 캠페인에 참가하거나 새 캠페인을 시작합니다.')
    async def campaign_join(ctx:commands.Context)->None:
        c=row(ctx)['campaign']; uid=int(ctx.author.id)
        if not c['active']: c.update({'active':True,'chapter':1,'members':[uid],'choices':[],'ending':None,'started_at':int(time.time())})
        elif uid not in c['members']: c['members'].append(uid)
        save_data(); await ctx.send(_text(loc(ctx),'📖 캠페인 통신망에 연결했습니다.','📖 Connected to the campaign network.'))

    @bot.command(name='행동선택',aliases=['chooseaction','abysschoice'],help='캠페인에서 전투·협상·탐사 중 하나를 선택합니다.')
    async def campaign_choice(ctx:commands.Context,선택:str)->None:
        c=row(ctx)['campaign']; l=loc(ctx); choices={'전투':'battle','협상':'negotiate','탐사':'explore','battle':'battle','negotiate':'negotiate','explore':'explore'}; key=choices.get(str(선택).lower())
        if not c['active'] or not key: await ctx.send(_text(l,'선택: 전투 · 협상 · 탐사','Choices: battle · negotiate · explore')); return
        c['choices'].append({'user':int(ctx.author.id),'choice':key,'at':int(time.time())}); c['chapter']=1+len(c['choices'])//3
        if len(c['choices'])>=9: c['ending']='rift_guardians'; c['active']=False; row(ctx)['lineage'].append({'type':'campaign_ending','ending':c['ending'],'at':int(time.time())})
        save_data(); await ctx.send(_text(l,f"🎭 **{선택}** 선택 기록 · 현재 챕터 {c['chapter']}",f"🎭 **{key}** recorded · Chapter {c['chapter']}"))

    # Crew / ship / raid ------------------------------------------------------------
    @bot.command(name='크루',aliases=['crew','crewstatus'],help='내 크루 또는 서버 크루 목록을 표시합니다.')
    async def crew_status(ctx:commands.Context)->None:
        crews=row(ctx)['crews']; uid=int(ctx.author.id); found=next(((n,c) for n,c in crews.items() if uid in c.get('members',[])),None); l=loc(ctx)
        if found:
            name,c=found; await ctx.send(_text(l,f"👥 **{name}** · 멤버 {len(c['members'])} · 레벨 {c['level']} · 임무 {c['missions']}",f"👥 **{name}** · {len(c['members'])} members · Level {c['level']} · Missions {c['missions']}"))
        else: await ctx.send(_text(l,'👥 소속 크루가 없습니다. `!크루창설 이름`','👥 You are not in a crew. `!createcrew name`'))

    @bot.command(name='크루창설',aliases=['createcrew'],help='새 고정 파티 크루를 창설합니다.')
    async def crew_create(ctx:commands.Context,*,이름:str)->None:
        n=row(ctx); name=' '.join(이름.split())[:30]; uid=int(ctx.author.id)
        if any(uid in c.get('members',[]) for c in n['crews'].values()): await ctx.send(_text(loc(ctx),'이미 크루에 소속되어 있습니다.','You already belong to a crew.')); return
        if name in n['crews']: await ctx.send(_text(loc(ctx),'같은 이름의 크루가 있습니다.','A crew with that name already exists.')); return
        n['crews'][name]={'owner':uid,'members':[uid],'level':1,'xp':0,'missions':0,'history':[{'type':'created','at':int(time.time())}]}; save_data(); await ctx.send(_text(loc(ctx),f"👥 크루 **{name}** 창설!",f"👥 Crew **{name}** created!"))

    @bot.command(name='크루임무',aliases=['crewmission'],help='크루 공동 임무를 진행합니다.')
    async def crew_mission(ctx:commands.Context)->None:
        n=row(ctx); uid=int(ctx.author.id); found=next(((nm,c) for nm,c in n['crews'].items() if uid in c.get('members',[])),None)
        if not found: await ctx.send(_text(loc(ctx),'크루에 먼저 가입하세요.','Join a crew first.')); return
        nm,c=found; gain=random.randint(12,30); c['xp']+=gain; c['missions']+=1
        if c['xp']>=c['level']*100: c['xp']-=c['level']*100;c['level']+=1
        c['history'].append({'type':'mission','gain':gain,'at':int(time.time())}); c['history']=c['history'][-50:]; save_data(); await ctx.send(_text(loc(ctx),f"🚀 **{nm}** 임무 완료 · XP +{gain} · Lv.{c['level']}",f"🚀 **{nm}** mission complete · XP +{gain} · Lv.{c['level']}"))

    @bot.command(name='우주선',aliases=['spaceship','abyssship'],help='서버 공동 차원 우주선 상태를 표시합니다.')
    async def spaceship(ctx:commands.Context)->None:
        s=row(ctx)['ship']; l=loc(ctx); lines=' · '.join(f"{k} Lv.{v}" for k,v in s['facilities'].items())
        await ctx.send(_text(l,f"🚀 **{s['name']}** Lv.{s['level']} · XP {s['xp']}\n{lines}",f"🚀 **{s['name']}** Lv.{s['level']} · XP {s['xp']}\n{lines}"))

    @bot.command(name='시설강화',aliases=['upgradefacility','shipupgrade'],help='서버 공동 우주선 시설을 강화합니다.')
    async def facility_upgrade(ctx:commands.Context,시설:str)->None:
        s=row(ctx)['ship']; key=next((k for k in s['facilities'] if 시설 in {k,k.replace(' ','')}),None)
        if not key: await ctx.send(_text(loc(ctx),'시설: '+' · '.join(s['facilities']),'Facilities: '+' · '.join(s['facilities']))); return
        s['facilities'][key]+=1; s['xp']+=20; s['level']=1+s['xp']//150; save_data(); await ctx.send(_text(loc(ctx),f"⚙️ {key} Lv.{s['facilities'][key]} 강화 완료",f"⚙️ {key} upgraded to Lv.{s['facilities'][key]}"))

    @bot.command(name='차원기지',aliases=['dimensionbase','riftbase'],help='서버 차원 기지와 우주선 시설을 한 화면에 표시합니다.')
    async def dimension_base(ctx:commands.Context)->None:
        n=row(ctx); srow=n['ship']; active=n['dimensions'].get('active'); l=loc(ctx)
        e=discord.Embed(title=_text(l,'🚀 ABYSS 차원 기지','🚀 ABYSS Dimension Base'),color=0x34495E)
        e.add_field(name=_text(l,'우주선','Ship'),value=f"{srow['name']} · Lv.{srow['level']} · XP {srow['xp']}",inline=False)
        e.add_field(name=_text(l,'시설','Facilities'),value='\n'.join(f"• {k} Lv.{v}" for k,v in srow['facilities'].items()),inline=True)
        e.add_field(name=_text(l,'현재 좌표','Current Coordinate'),value=((active['ko'] if l=='ko' else active['en'])+f" · {active['progress']}%") if active else _text(l,'대기 중','Idle'),inline=True)
        await ctx.send(embed=e)

    @bot.command(name='항해출발',aliases=['launchvoyage','startvoyage'],help='서버 우주선으로 선택한 차원 또는 무작위 차원 항해를 시작합니다.')
    async def launch_voyage(ctx:commands.Context,*,차원:str='')->None:
        user=await registered(ctx)
        if user is None:return
        n=row(ctx); dims=n['dimensions']; l=loc(ctx)
        if dims.get('active'): await ctx.send(_text(l,'이미 진행 중인 차원이 있습니다.','A dimension voyage is already active.')); return
        token=''.join(str(차원).lower().split()); spec=None
        for item in DIMENSIONS:
            if token and token in {item['id'].lower(),''.join(item['ko'].split()),''.join(item['en'].lower().split())}: spec=deepcopy(item); break
        if spec is None: spec=deepcopy(random.choice(DIMENSIONS))
        engine=int(n['ship']['facilities'].get('차원엔진',1)); spec.update({'progress':min(12,engine*2),'started_at':int(time.time()),'members':[int(ctx.author.id)]}); dims['active']=spec; dims['discovered']=list(dict.fromkeys(dims.get('discovered',[])+[spec['id']])); n['ship']['xp']+=5; save_data()
        await ctx.send(_text(l,f"🚀 **{spec['ko']}** 항해 출발 · 초기 안정도 {spec['progress']}%",f"🚀 Voyage launched to **{spec['en']}** · Initial stability {spec['progress']}%"))

    @bot.command(name='연합망',aliases=['federationnetwork','servernetwork'],help='서버 연합망 참여 상태를 확인하거나 켜고 끕니다.')
    @commands.has_guild_permissions(manage_guild=True)
    async def federation_network(ctx:commands.Context,상태:str='')->None:
        n=row(ctx); l=loc(ctx); maps={'켜기':True,'on':True,'enable':True,'끄기':False,'off':False,'disable':False}; key=maps.get(str(상태).lower())
        if key is not None: n['settings']['network_opt_in']=key; save_data()
        await ctx.send(_text(l,f"🌐 서버 연합망: **{'켜짐' if n['settings'].get('network_opt_in') else '꺼짐'}** · 초대와 공개 콘텐츠는 양쪽 관리자 동의가 필요합니다.",f"🌐 Federation network: **{'ON' if n['settings'].get('network_opt_in') else 'OFF'}** · Invites and shared content require admin opt-in on both sides."))

    @bot.command(name='서버연합',aliases=['serverfederation','federation'],help='서버 연합을 만들거나 받은 초대를 승인해 가입합니다.')
    @commands.has_guild_permissions(manage_guild=True)
    async def server_federation(ctx:commands.Context,*,이름:str='')->None:
        n=row(ctx); l=loc(ctx); gid=str(int(ctx.guild.id)); name=' '.join(str(이름).split())[:40]
        current=next(((fn,f) for fn,f in root['federations'].items() if gid in f.get('guilds',[])),None)
        if not name:
            if current: await ctx.send(_text(l,f"🌐 소속 연합 **{current[0]}** · 서버 {len(current[1]['guilds'])}개",f"🌐 Federation **{current[0]}** · {len(current[1]['guilds'])} servers"))
            else: await ctx.send(_text(l,'소속 서버 연합이 없습니다.','This server is not in a federation.'))
            return
        if not n['settings'].get('network_opt_in'): await ctx.send(_text(l,'먼저 `!연합망 켜기`가 필요합니다.','Enable the network first with `!federationnetwork on`.')); return
        if current: await ctx.send(_text(l,'이미 다른 서버 연합에 소속되어 있습니다.','This server already belongs to a federation.')); return
        fed=root['federations'].get(name)
        if fed is None:
            root['federations'][name]={'owner_guild':gid,'guilds':[gid],'invites':[],'created_at':int(time.time()),'history':[]}; save_data(); await ctx.send(_text(l,f"🌐 서버 연합 **{name}** 창설 완료",f"🌐 Server federation **{name}** created")); return
        if gid not in fed.get('invites',[]): await ctx.send(_text(l,'해당 연합의 초대가 없습니다.','No invitation from that federation.')); return
        fed['invites'].remove(gid); fed['guilds'].append(gid); fed['guilds']=list(dict.fromkeys(fed['guilds'])); fed['history'].append({'type':'join','guild':gid,'at':int(time.time())}); save_data(); await ctx.send(_text(l,f"✅ 서버 연합 **{name}** 가입 완료",f"✅ Joined server federation **{name}**"))

    @bot.command(name='연합초대',aliases=['federationinvite','inviteserver'],help='연합 소유 서버가 연합망을 켠 다른 서버를 ID로 초대합니다.')
    @commands.has_guild_permissions(manage_guild=True)
    async def federation_invite(ctx:commands.Context,서버ID:str)->None:
        gid=str(int(ctx.guild.id)); target=''.join(ch for ch in str(서버ID) if ch.isdigit()); l=loc(ctx)
        found=next(((fn,f) for fn,f in root['federations'].items() if f.get('owner_guild')==gid),None)
        if not found: await ctx.send(_text(l,'이 서버가 소유한 연합이 없습니다.','This server does not own a federation.')); return
        target_row=root['guilds'].get(target)
        if not target_row or not target_row.get('settings',{}).get('network_opt_in'): await ctx.send(_text(l,'대상 서버가 봇 데이터에 없거나 연합망을 켜지 않았습니다.','Target server is unavailable or has not opted into the network.')); return
        found[1].setdefault('invites',[]).append(target); found[1]['invites']=list(dict.fromkeys(found[1]['invites'])); save_data(); await ctx.send(_text(l,f"📨 서버 `{target}`에 **{found[0]}** 초대 기록을 만들었습니다.",f"📨 Invitation to **{found[0]}** created for server `{target}`."))

    @bot.command(name='연합순위',aliases=['federationranking','servernetworkranking'],help='연합망에 참여한 서버 연합 순위를 집계합니다.')
    async def federation_ranking(ctx:commands.Context)->None:
        l=loc(ctx); rows=[]
        for name,fed in root['federations'].items():
            score=0
            for gid in fed.get('guilds',[]):
                gr=root['guilds'].get(str(gid),{}); score+=int(gr.get('ship',{}).get('level',1))*100+len(gr.get('dimensions',{}).get('history',[]))*50+len(gr.get('lineage',[]))*5
            rows.append((score,name,len(fed.get('guilds',[]))))
        rows.sort(reverse=True); lines=[f"**{i}. {name}** · {count} servers · {score:,} pts" for i,(score,name,count) in enumerate(rows[:10],1)]
        await ctx.send(embed=discord.Embed(title=_text(l,'🌐 서버 연합 순위','🌐 Federation Ranking'),description='\n'.join(lines) if lines else _text(l,'등록된 연합이 없습니다.','No federations registered.'),color=0x2980B9))

    @bot.command(name='공격대',aliases=['dimensionraid','abyssraid'],help='차원 공격대 보스 상태를 표시합니다.')
    async def raid_status(ctx:commands.Context)->None:
        r=row(ctx).get('raid'); l=loc(ctx)
        if not r: await ctx.send(_text(l,'👹 공격대 보스가 없습니다. 관리자가 `!공격대소환`으로 시작할 수 있습니다.','👹 No raid boss. An admin can use `!summonriftboss`.')); return
        bar='█'*int(20*r['hp']/r['max_hp'])+'░'*(20-int(20*r['hp']/r['max_hp']))
        await ctx.send(_text(l,f"👹 **{r['name_ko']}** · 단계 {r['phase']}\n`{bar}` {r['hp']:,}/{r['max_hp']:,}",f"👹 **{r['name_en']}** · Phase {r['phase']}\n`{bar}` {r['hp']:,}/{r['max_hp']:,}"))

    @bot.command(name='공격대소환',aliases=['summonriftboss'],help='관리자가 연출형 차원 보스를 소환합니다.')
    @commands.has_guild_permissions(manage_guild=True)
    async def raid_summon(ctx:commands.Context)->None:
        n=row(ctx); hp=1_000_000+len(getattr(ctx.guild,'members',[]))*25_000; n['raid']={'id':f"RAID-{int(time.time())}",'name_ko':'아바돈의 분신','name_en':'Fragment of ABADDON','hp':hp,'max_hp':hp,'phase':1,'members':{},'started_at':int(time.time())}; save_data(); await ctx.send(_text(loc(ctx),f"🌑 차원 보스 출현! HP {hp:,}",f"🌑 Rift boss appeared! HP {hp:,}"))

    @bot.command(name='공격대참가',aliases=['joinraid'],help='현재 차원 공격대에 참가합니다.')
    async def raid_join(ctx:commands.Context)->None:
        r=row(ctx).get('raid')
        if not r: await ctx.send(_text(loc(ctx),'공격대가 없습니다.','No active raid.')); return
        r['members'].setdefault(str(ctx.author.id),{'damage':0,'support':0}); save_data(); await ctx.send(_text(loc(ctx),'🛡️ 공격대에 합류했습니다.','🛡️ Joined the raid.'))

    @bot.command(name='차원보스공격',aliases=['riftbossattack','attackriftboss'],help='차원 보스의 약점을 공격합니다.')
    async def boss_attack(ctx:commands.Context)->None:
        user=await registered(ctx)
        if user is None:return
        n=row(ctx); r=n.get('raid')
        if not r: await ctx.send(_text(loc(ctx),'활성 공격대가 없습니다.','No active raid.')); return
        m=r['members'].setdefault(str(ctx.author.id),{'damage':0,'support':0}); damage=random.randint(18000,52000); crit=random.random()<0.18
        if crit: damage*=2
        r['hp']=max(0,r['hp']-damage); m['damage']+=damage; r['phase']=min(4,1+int((1-r['hp']/r['max_hp'])*4))
        if r['hp']==0:
            reward=15000; user['balance']=int(user.get('balance',0))+reward; n['lineage'].append({'type':'raid_clear','id':r['id'],'at':int(time.time()),'members':list(r['members'])}); n['raid']=None; text=_text(loc(ctx),f"🏆 최종 타격 {damage:,}! 보스 격파 · {reward:,}칩",f"🏆 Final strike {damage:,}! Boss defeated · {reward:,} chips")
        else:text=_text(loc(ctx),f"{'⚡ 치명타! ' if crit else '⚔️ '}{damage:,} 피해 · 보스 HP {r['hp']:,}",f"{'⚡ Critical! ' if crit else '⚔️ '}{damage:,} damage · Boss HP {r['hp']:,}")
        save_data(); await ctx.send(text)

    @bot.command(name='보스방어',aliases=['bossdefend','raiddefend'],help='공격대 방어 태세로 지원 점수를 올립니다.')
    async def boss_defend(ctx:commands.Context)->None:
        r=row(ctx).get('raid')
        if not r: await ctx.send(_text(loc(ctx),'활성 공격대가 없습니다.','No active raid.')); return
        m=r['members'].setdefault(str(ctx.author.id),{'damage':0,'support':0}); m['support']+=random.randint(10,25); save_data(); await ctx.send(_text(loc(ctx),f"🛡️ 방어막 전개 · 지원 {m['support']}",f"🛡️ Barrier deployed · Support {m['support']}"))

    # Creator, replay and lineage ---------------------------------------------------
    @bot.command(name='창작센터',aliases=['creatorstudio','contentstudio'],help='서버 사용자 제작 콘텐츠 현황을 확인합니다.')
    async def creator_studio(ctx:commands.Context)->None:
        s=row(ctx)['studio']; await ctx.send(_text(loc(ctx),f"🧰 초안 {len(s['drafts'])}개 · 공개 {len(s['published'])}개\n`!퀘스트제작 제목 | 설명`",f"🧰 {len(s['drafts'])} drafts · {len(s['published'])} published\n`!createquest title | description`"))

    @bot.command(name='보스제작',aliases=['createboss','bosscreator'],help='서버 전용 공격대 보스 초안을 제작합니다.')
    @commands.has_guild_permissions(manage_guild=True)
    async def create_boss(ctx:commands.Context,*,내용:str)->None:
        parts=[x.strip() for x in 내용.split('|')]
        if len(parts)<2: await ctx.send(_text(loc(ctx),'형식: !보스제작 이름 | HP | 설명','Format: !createboss name | HP | description')); return
        try: hp=max(50000,min(10000000,int(parts[1].replace(',',''))))
        except Exception: hp=500000
        bid=f"B-{random.randint(100000,999999)}"; row(ctx)['studio']['drafts'][bid]={'id':bid,'type':'boss','title':parts[0][:60],'hp':hp,'description':(parts[2] if len(parts)>2 else '')[:400],'author':int(ctx.author.id),'version':1,'status':'draft'}; save_data(); await ctx.send(_text(loc(ctx),f"👹 보스 초안 `{bid}` · HP {hp:,}",f"👹 Boss draft `{bid}` · HP {hp:,}"))

    @bot.command(name='퀘스트제작',aliases=['createquest'],help='검수 가능한 사용자 제작 퀘스트 초안을 만듭니다.')
    @commands.has_guild_permissions(manage_guild=True)
    async def create_quest(ctx:commands.Context,*,내용:str)->None:
        parts=[x.strip() for x in 내용.split('|',1)]
        if len(parts)<2: await ctx.send(_text(loc(ctx),'형식: !퀘스트제작 제목 | 설명','Format: !createquest title | description')); return
        qid=f"Q-{random.randint(100000,999999)}"; row(ctx)['studio']['drafts'][qid]={'id':qid,'title':parts[0][:60],'description':parts[1][:400],'author':int(ctx.author.id),'reward':1000,'version':1,'status':'draft'}; save_data(); await ctx.send(_text(loc(ctx),f"🧰 퀘스트 초안 `{qid}` 생성",f"🧰 Quest draft `{qid}` created"))

    @bot.command(name='콘텐츠공개',aliases=['publishcontent'],help='검수된 사용자 제작 콘텐츠를 서버에 공개합니다.')
    @commands.has_guild_permissions(manage_guild=True)
    async def publish_content(ctx:commands.Context,콘텐츠ID:str)->None:
        s=row(ctx)['studio']; q=s['drafts'].pop(콘텐츠ID,None)
        if not q: await ctx.send(_text(loc(ctx),'초안을 찾지 못했습니다.','Draft not found.')); return
        q['status']='published'; q['published_at']=int(time.time()); s['published'][콘텐츠ID]=q
        if row(ctx)['settings'].get('network_opt_in') and row(ctx)['settings'].get('content_share'):
            root['exchange'][콘텐츠ID]={**deepcopy(q),'source_guild':str(int(ctx.guild.id)),'source_name':str(ctx.guild.name)[:60]}
        save_data(); await ctx.send(_text(loc(ctx),f"✅ **{q['title']}** 공개 완료",f"✅ **{q['title']}** published"))

    @bot.command(name='콘텐츠공유',aliases=['contentsharing','sharecontent'],help='서버 제작 콘텐츠의 연합망 공유를 켜거나 끕니다.')
    @commands.has_guild_permissions(manage_guild=True)
    async def content_sharing(ctx:commands.Context,상태:str='')->None:
        n=row(ctx); maps={'켜기':True,'on':True,'enable':True,'끄기':False,'off':False,'disable':False}; key=maps.get(str(상태).lower())
        if key is not None: n['settings']['content_share']=key; save_data()
        await ctx.send(_text(loc(ctx),f"🧩 콘텐츠 공유: **{'켜짐' if n['settings'].get('content_share') else '꺼짐'}**",f"🧩 Content sharing: **{'ON' if n['settings'].get('content_share') else 'OFF'}**"))

    @bot.command(name='콘텐츠검색',aliases=['contentsearch','searchcontent'],help='연합망에 공개된 사용자 콘텐츠를 검색합니다.')
    async def content_search(ctx:commands.Context,*,검색어:str='')->None:
        q=str(검색어).casefold().strip(); l=loc(ctx); rows=[]
        for cid,item in root['exchange'].items():
            hay=f"{item.get('title','')} {item.get('description','')} {item.get('source_name','')}".casefold()
            if not q or q in hay: rows.append(f"`{cid}` **{item.get('title','Untitled')}** · {item.get('source_name','Server')}")
        await ctx.send(embed=discord.Embed(title=_text(l,'🔎 콘텐츠 검색','🔎 Content Search'),description='\n'.join(rows[:20]) if rows else _text(l,'검색 결과가 없습니다.','No results.'),color=0x1F618D))

    @bot.command(name='콘텐츠설치',aliases=['contentinstall','installcontent'],help='연합망 공개 콘텐츠를 현재 서버에 복제 설치합니다.')
    @commands.has_guild_permissions(manage_guild=True)
    async def content_install(ctx:commands.Context,콘텐츠ID:str)->None:
        source=root['exchange'].get(콘텐츠ID)
        if not source: await ctx.send(_text(loc(ctx),'공개 콘텐츠를 찾지 못했습니다.','Shared content not found.')); return
        clone=deepcopy(source); clone_id=f"{콘텐츠ID}-I{random.randint(100,999)}"; clone['id']=clone_id; clone['installed_from']=콘텐츠ID; clone['status']='published'; clone['version']=int(clone.get('version',1)); row(ctx)['studio']['published'][clone_id]=clone; save_data(); await ctx.send(_text(loc(ctx),f"📦 **{clone.get('title')}** 설치 완료 · `{clone_id}`",f"📦 **{clone.get('title')}** installed · `{clone_id}`"))

    @bot.command(name='콘텐츠교환소',aliases=['contentexchange','contentmarketplace'],help='현재 서버에서 공개한 사용자 콘텐츠를 표시합니다.')
    async def content_exchange(ctx:commands.Context)->None:
        pub=row(ctx)['studio']['published']; lines=[f"`{i}` **{q['title']}** v{q['version']}" for i,q in pub.items()]
        await ctx.send(embed=discord.Embed(title=_text(loc(ctx),'🧩 콘텐츠 교환소','🧩 Content Exchange'),description='\n'.join(lines) if lines else _text(loc(ctx),'공개 콘텐츠가 없습니다.','No published content.'),color=0x2980B9))

    @bot.command(name='경기요약',aliases=['matchsummary','replaysummary'],help='최근 공개 기록으로 간단한 경기 요약을 저장합니다.')
    async def match_summary(ctx:commands.Context)->None:
        n=row(ctx); rid=f"RP-{random.randint(100000,999999)}"; item={'id':rid,'at':int(time.time()),'author':int(ctx.author.id),'title':_text(loc(ctx),'도시 명장면','City Highlight')}; n['replays'].append(item); n['replays']=n['replays'][-50:]; save_data(); await ctx.send(_text(loc(ctx),f"🎬 리플레이 `{rid}` 저장 · 비공개 패는 포함하지 않았습니다.",f"🎬 Replay `{rid}` saved · Private hands were excluded."))

    @bot.command(name='리플레이',aliases=['replaystudio','replaylist'],help='저장된 공개 경기 요약과 명장면을 표시합니다.')
    async def replay_studio(ctx:commands.Context)->None:
        records=row(ctx)['replays'][-15:][::-1]; lines=[f"`{r.get('id')}` · {r.get('title')} · <t:{int(r.get('at',0))}:R>" for r in records]
        await ctx.send(embed=discord.Embed(title=_text(loc(ctx),'🎬 리플레이 스튜디오','🎬 Replay Studio'),description='\n'.join(lines) if lines else _text(loc(ctx),'저장된 공개 리플레이가 없습니다.','No public replays saved.'),color=0x884EA0))

    @bot.command(name='세계연표',aliases=['worldtimeline','dimensiontimeline'],help='차원 발견·캠페인 결말·보스 격파를 시간순으로 표시합니다.')
    async def world_timeline(ctx:commands.Context)->None:
        records=sorted(row(ctx)['lineage'],key=lambda x:int(x.get('at',0)),reverse=True)[:20]; lines=[f"• <t:{int(r.get('at',0))}:d> `{r.get('type')}` {r.get('id',r.get('ending',''))}" for r in records]
        await ctx.send(embed=discord.Embed(title=_text(loc(ctx),'🕰️ 세계 연표','🕰️ World Timeline'),description='\n'.join(lines) if lines else _text(loc(ctx),'기록된 세계 사건이 없습니다.','No world events recorded.'),color=0x512E5F))

    @bot.command(name='차원계보',aliases=['dimensionlineage','worldlineage'],help='도시의 차원·캠페인·보스 영구 기록을 표시합니다.')
    async def dimension_lineage(ctx:commands.Context)->None:
        records=row(ctx)['lineage'][-15:][::-1]; lines=[]
        for r in records: lines.append(f"• `{r.get('type')}` · <t:{int(r.get('at',0))}:R> · {r.get('id',r.get('ending',''))}")
        await ctx.send(embed=discord.Embed(title=_text(loc(ctx),'📜 차원 계보','📜 Dimension Lineage'),description='\n'.join(lines) if lines else _text(loc(ctx),'아직 영구 기록이 없습니다.','No permanent records yet.'),color=0x5B2C6F))

    @bot.command(name='대화모드',aliases=['chatmode','conversationmode'],help='아바돈 대화를 문맥형 또는 기존 기본형으로 전환합니다.')
    async def conversation_mode(ctx:commands.Context,모드:str='')->None:
        l=loc(ctx); state=world_data.setdefault('dialogue_memory_v620',{}).setdefault(str(int(ctx.guild.id)),{}); settings=state.setdefault('settings',{})
        maps={'문맥형':'contextual','자연스럽게':'contextual','contextual':'contextual','기본형':'classic','classic':'classic'}
        key=maps.get(str(모드).lower())
        if key: settings['v1500_mode']=key; save_data()
        current=settings.get('v1500_mode','contextual')
        await ctx.send(_text(l,f"💬 현재 대화 모드: **{current}** · 문맥형은 이전 대화 주제와 짧은 후속 답변을 이어갑니다.",f"💬 Current chat mode: **{current}** · Contextual mode follows prior topics and short replies."))

    @bot.command(name='대화상태',aliases=['chatstatus','conversationstatus'],help='문맥형 대화의 언어·보존 시간·기억 상태를 확인합니다.')
    async def conversation_status(ctx:commands.Context)->None:
        l=loc(ctx); state=world_data.setdefault('dialogue_memory_v620',{}).setdefault(str(int(ctx.guild.id)),{}); settings=state.setdefault('settings',{})
        profile=state.setdefault('profiles',{}).get(str(int(ctx.author.id)),{})
        e=discord.Embed(title=_text(l,'💬 ABADDON 대화 상태','💬 ABADDON Chat Status'),color=0x4A235A)
        e.add_field(name=_text(l,'모드','Mode'),value=str(settings.get('v1500_mode','contextual')),inline=True)
        e.add_field(name=_text(l,'연속 대화','Continuous Chat'),value=_text(l,'60분 · 최대 100턴','60 minutes · up to 100 turns'),inline=True)
        e.add_field(name=_text(l,'교감 기록','Bond Record'),value=f"{int(profile.get('conversation_count',0))} turns",inline=True)
        e.add_field(name=_text(l,'언어 처리','Language'),value=_text(l,'메시지별 한국어/English 분리','Per-message Korean/English separation'),inline=False)
        await ctx.send(embed=e)

    @bot.command(name='대화기억요약',aliases=['conversationmemory','chatmemorysummary'],help='내 서버 대화·기억 사용 통계를 요약합니다.')
    async def conversation_memory_summary(ctx:commands.Context)->None:
        l=loc(ctx); state=world_data.setdefault('dialogue_memory_v620',{}).setdefault(str(int(ctx.guild.id)),{}); stats=state.setdefault('stats',{}); profile=state.setdefault('profiles',{}).get(str(int(ctx.author.id)),{})
        text=_text(l,f"🧠 내 대화 {int(profile.get('conversation_count',0))}회 · 서버 대화 {int(stats.get('conversations',0))}회 · 승인 기억 사용 {int(stats.get('learned_hits',0))}회",f"🧠 My turns {int(profile.get('conversation_count',0))} · Server turns {int(stats.get('conversations',0))} · Approved-memory hits {int(stats.get('learned_hits',0))}")
        await ctx.send(text)

    @bot.command(name='1500통합검수',aliases=['v1500audit'],help='v15.0 기능·영문 접근·글꼴·자산·상태를 읽기 전용 검사합니다.')
    async def v1500_audit(ctx:commands.Context,상세:str='')->None:
        required=['도시지도','도시꾸미기','도시부품','연출설정','차원문','차원탐사','크루','우주선','공격대','차원보스공격','창작센터','차원기지','연합망','서버연합','콘텐츠검색','콘텐츠설치','리플레이','세계연표','대화모드','대화상태','차원계보']
        checks=[('commands',all(bot.get_command(x) is not None for x in required),f"{sum(bot.get_command(x) is not None for x in required)}/{len(required)}"),('english aliases',all(any(re.fullmatch(r'[a-z0-9_-]+',a) for a in getattr(bot.get_command(x),'aliases',[])) for x in required),required),('font',font_status['loaded'],font_status['name']),('components',all(_safe_component_path(x) for x in COMPONENT_LABELS),len(COMPONENT_LABELS)),('conversation hook',callable(getattr(bot,'_abaddon_v1500_conversation_reply',None)),'contextual bilingual')]
        e=discord.Embed(title='🧪 ABADDON v15.0 Integration Audit',description='\n'.join(f"{'✅' if ok else '❌'} **{name}** · {detail}" for name,ok,detail in checks),color=0x2ECC71 if all(x[1] for x in checks) else 0xE74C3C)
        await ctx.send(embed=e)

    # Keep the shared latest-patch commands synchronized with v15.0.
    patch_cmd = bot.get_command('패치노트')
    if patch_cmd is not None:
        previous_patch = patch_cmd.callback
        async def v1500_patch_notes(ctx:commands.Context,*args:Any,**kwargs:Any)->None:
            l=loc(ctx)
            e=discord.Embed(
                title=_text(l,'🌌 ABADDON v15.0.0 — NEON ABYSS','🌌 ABADDON v15.0.0 — NEON ABYSS'),
                description=_text(l,'v14.2 차원 항해 계획과 v15.0 시각·연출·대화 확장을 하나로 통합했습니다. 기존 BLACK CITY와 저장 데이터는 유지됩니다.','Integrates the v14.2 dimension-voyage plan with the v15 visual, FX and conversation expansion. Existing BLACK CITY saves remain intact.'),
                color=0x8E44AD,
            )
            e.add_field(name=_text(l,'🏙️ 도시 시각화','🏙️ City Visuals'),value=_text(l,'한글 안전 레이어 지도 · 개별 도시 부품 20종 · 배치 드롭다운 · 미리보기·복구·사진','Korean-safe layered map · 20 city parts · selector placement · preview, rollback and photos'),inline=False)
            e.add_field(name=_text(l,'✨ 행동 연출','✨ Action Effects'),value=_text(l,'채집·제작·보스·탐험·건설·거래의 시작→진행→판정→결과 연출 · Unicode 이모지 폴백','Start→progress→resolution→result FX for gathering, crafting, bosses, exploration, construction and trades · Unicode fallback'),inline=False)
            e.add_field(name=_text(l,'🌌 신규 세계','🌌 New World Systems'),value=_text(l,'차원 항해 · 캠페인 · 크루 · 공동 우주선 · 4단계 공격대 · 창작센터 · 리플레이·계보','Dimension voyages · campaigns · crews · shared ship · four-stage raids · creator studio · replay and lineage'),inline=False)
            e.add_field(name=_text(l,'💬 대화','💬 Conversation'),value=_text(l,'60분·100턴 문맥 유지 · 짧은 후속 답변 연결 · 메시지별 한국어/English 분리','60-minute, 100-turn context · short follow-up continuity · per-message Korean/English separation'),inline=False)
            e.add_field(name=_text(l,'🧪 검수','🧪 Audit'),value=_text(l,'`!1500시각검수 상세` · `!1500통합검수 상세` · `!명령등록검수 상세`','`!v1500visualaudit detail` · `!v1500audit detail` · `!commandregistryaudit detail`'),inline=False)
            e.set_footer(text='2026-08-05 · NEON ABYSS · Korean / English synchronized')
            await ctx.send(embed=e)
        patch_cmd.callback=v1500_patch_notes
        patch_cmd.help='ABADDON v15.0.0 NEON ABYSS 최신 패치노트를 표시합니다.'
        patch_cmd.description=patch_cmd.help
        patch_cmd.extras=dict(getattr(patch_cmd,'extras',{}) or {})
        patch_cmd.extras['v1500_previous_callback']=previous_patch

    test_cmd = bot.get_command('테스트')
    if test_cmd is not None:
        previous_test = test_cmd.callback
        async def v1500_latest_test(ctx:commands.Context,*args:Any,**kwargs:Any)->None:
            mode=' '.join(str(x) for x in args) if args else str(kwargs.get('상세',kwargs.get('mode','')))
            command=bot.get_command('1500통합검수')
            if command is not None:
                await ctx.invoke(command, 상세='상세' if mode.strip().lower() in {'상세','detail','detailed','full'} else '')
            else:
                await ctx.send(_text(loc(ctx),'❌ v15.0 검수 명령을 찾지 못했습니다.','❌ v15.0 audit command was not found.'))
        test_cmd.callback=v1500_latest_test
        test_cmd.help='가장 최근 v15.0.0 변경 범위만 읽기 전용으로 검사합니다.'
        test_cmd.description=test_cmd.help
        test_cmd.extras=dict(getattr(test_cmd,'extras',{}) or {})
        test_cmd.extras['v1500_previous_callback']=previous_test

    # Visual action listeners. They do not replace the original result, so old game logic remains intact.
    async def fx_start(ctx:commands.Context)->None:
        if ctx.guild is None or ctx.command is None:return
        # v18.1.3: button-bridged commands skip cinematic pre-messages. The
        # original button panel is already visible and the real result should be
        # the only new Discord response, minimizing 1015-prone request bursts.
        if bool(getattr(ctx, '_v1813_button_bridge', False)): return
        n=row(ctx); mode=n['settings'].get('effects','cinematic')
        if mode=='off':return
        key=str(ctx.command.name); profile=FX_PROFILES.get(key)
        if not profile:return
        l=loc(ctx); lines=profile['en_lines'] if l=='en' else profile['ko']; shown=lines[:2] if mode=='compact' else lines
        msg=await ctx.send(shown[0]); task=None
        async def animate():
            try:
                for line in shown[1:]: await asyncio.sleep(0.55); await msg.edit(content=line)
            except Exception: pass
        task=asyncio.create_task(animate()); active_fx[int(ctx.message.id)]={'message':msg,'task':task,'profile':profile,'locale':l}; n['stats']['fx_started']=int(n['stats'].get('fx_started',0))+1
    async def fx_complete(ctx:commands.Context)->None:
        item=active_fx.pop(int(getattr(ctx.message,'id',0)),None)
        if not item:return
        task=item.get('task');
        if task and not task.done(): task.cancel()
        p=item['profile']; l=item['locale']; final={'gather':('🎉 채집 완료 · 결과를 확인하세요','🎉 Gathering complete · Check the result'),'craft':('🏆 제작 완료 · 품질과 보상을 확인하세요','🏆 Crafting complete · Check quality and rewards'),'boss':('📊 전투 처리 완료 · 피해와 보상 판정','📊 Combat resolved · Damage and rewards calculated'),'explore':('🗺️ 탐험 결과 확정','🗺️ Exploration result confirmed'),'build':('🏗️ 건설 기록 갱신 완료','🏗️ Construction record updated'),'trade':('✅ 안전 거래 처리 완료','✅ Secure trade completed')}.get(p['kind'],('✨ 처리 완료','✨ Complete'))
        try: await item['message'].edit(content=final[1] if l=='en' else final[0])
        except Exception: pass
    async def fx_error(ctx:commands.Context,error:Exception)->None:
        item=active_fx.pop(int(getattr(ctx.message,'id',0)),None)
        if not item:return
        task=item.get('task');
        if task and not task.done(): task.cancel()
        try: await item['message'].edit(content='💔 Action failed · original error handler will provide details' if item['locale']=='en' else '💔 행동 실패 · 기존 오류 안내에서 상세 원인을 확인하세요')
        except Exception: pass
    bot.add_listener(fx_start,'on_command'); bot.add_listener(fx_complete,'on_command_completion'); bot.add_listener(fx_error,'on_command_error')

    bot._abaddon_v1500_conversation_reply=_conversation_reply
    bot._abaddon_v1500_font_status=font_status

    guide.append({"id":"v1500_neon_abyss","emoji":"🌌","title":"v15.0 NEON ABYSS","hint":"도시 레이어 꾸미기·행동 연출·차원·크루·공격대·자연스러운 연속 대화","commands":["!도시지도 · !도시꾸미기 · !도시부품 · !도시사진","!연출설정 · !연출도감 · !1500시각검수","!차원문 · !차원탐사 · !차원지도 · !차원기지 · !항해출발 · !캠페인","!크루 · !크루창설 · !크루임무 · !우주선 · !시설강화 · !연합망 · !서버연합","!공격대 · !공격대참가 · !차원보스공격 · !보스방어","!창작센터 · !퀘스트제작 · !보스제작 · !콘텐츠공개 · !콘텐츠검색 · !콘텐츠설치","!경기요약 · !리플레이 · !차원계보 · !세계연표 · !대화모드 · !대화상태 · !1500통합검수"]})
    print(f"[ABADDON v15.0.0] korean_font={'loaded' if font_status['loaded'] else 'fallback'} city_renderer=layered components={len(COMPONENT_LABELS)} visual_fx=enabled conversation=contextual-bilingual",flush=True)
