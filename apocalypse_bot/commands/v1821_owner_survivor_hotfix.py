from __future__ import annotations

"""ABADDON v18.2.1 owner survivor registry + contextual owner UI hotfix.

This module intentionally does not expose balances, inventory details, message
content, or command arguments in the roster. It is a creator-only operational
view over already-registered survivor records.
"""

import re
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v1811_presence_owner_servers import _private_owner

VERSION = "18.2.1"
PAGE_SIZE = 12


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _registration(user: Mapping[str, Any]) -> Mapping[str, Any]:
    value = user.get("registration", {})
    return value if isinstance(value, Mapping) else {}


def _registration_ts(user: Mapping[str, Any]) -> Optional[int]:
    raw = str(_registration(user).get("registered_at") or "").strip()
    if not raw:
        return None
    try:
        return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError, OverflowError):
        return None


def _cached_user(bot: commands.Bot, user_id: int) -> Optional[discord.abc.User]:
    user = bot.get_user(user_id)
    if user is not None:
        return user
    for guild in bot.guilds:
        member = guild.get_member(user_id)
        if member is not None:
            return member
    return None


def _display_name(bot: commands.Bot, user_id: int) -> str:
    user = _cached_user(bot, user_id)
    if user is None:
        return f"ID {user_id}"
    return str(getattr(user, "display_name", None) or getattr(user, "name", None) or user_id)


def _iter_survivors(user_data: Mapping[Any, Any]) -> List[Tuple[int, Mapping[str, Any]]]:
    rows: List[Tuple[int, Mapping[str, Any]]] = []
    for key, value in user_data.items():
        if not isinstance(value, Mapping):
            continue
        try:
            uid = int(key)
        except (TypeError, ValueError):
            continue
        rows.append((uid, value))
    # Newest known registrations first. Legacy users follow, then stable ID order.
    rows.sort(key=lambda row: (_registration_ts(row[1]) is not None, _registration_ts(row[1]) or 0, row[0]), reverse=True)
    return rows


def _extract_id(text: str) -> Optional[int]:
    raw = str(text or "").strip()
    if not raw:
        return None
    match = re.fullmatch(r"<@!?(\d{15,25})>", raw)
    if match:
        return int(match.group(1))
    if raw.isdigit():
        return int(raw)
    return None


def _find_by_name(bot: commands.Bot, user_data: Mapping[Any, Any], query: str) -> List[int]:
    token = str(query or "").strip().casefold()
    if not token:
        return []
    exact: List[int] = []
    partial: List[int] = []
    for uid, _record in _iter_survivors(user_data):
        user = _cached_user(bot, uid)
        if user is None:
            continue
        names = {
            str(getattr(user, "name", "") or "").casefold(),
            str(getattr(user, "display_name", "") or "").casefold(),
            str(user).casefold(),
        }
        if token in names:
            exact.append(uid)
        elif any(token in name for name in names if name):
            partial.append(uid)
    return exact or partial


async def _owner_dm(bot: commands.Bot, ctx: commands.Context) -> Optional[discord.abc.Messageable]:
    if not await _private_owner(bot, ctx.author):
        return None
    try:
        return ctx.author.dm_channel or await ctx.author.create_dm()
    except (discord.Forbidden, discord.HTTPException):
        try:
            await ctx.send("❌ DM을 열 수 없습니다. 제작자 계정의 DM 수신 설정을 확인해주세요.")
        except Exception:
            pass
        return None


async def _ack(ctx: commands.Context) -> None:
    if ctx.guild is None:
        return
    try:
        await ctx.message.add_reaction("✅")
    except (discord.Forbidden, discord.HTTPException, AttributeError):
        pass


def register_v1821_owner_survivor_hotfix(
    bot: commands.Bot,
    user_data: MutableMapping[Any, Any],
    save_data: Callable[[], None],
) -> None:
    if getattr(bot, "_abaddon_v1821_registered", False):
        return

    # v18.1.5 once used misleading guild aliases. Remove any surviving runtime
    # alias mappings so contextual classification can never mistake owner usage
    # telemetry for the guild/party gameplay category.
    for alias in ("길드사용로그", "길드사용통계"):
        mapped = bot.all_commands.get(alias)
        if mapped is not None and getattr(mapped, "name", "") in {"서버사용로그", "서버사용통계"}:
            bot.all_commands.pop(alias, None)
            try:
                mapped.aliases = [x for x in mapped.aliases if x != alias]
            except Exception:
                pass

    @bot.command(
        name="생존자수",
        aliases=["가입생존자수", "survivorcount"],
        hidden=True,
        help="[봇 소유자 전용] ABADDON에 가입한 전체 생존자 수를 DM으로 확인합니다.",
    )
    async def survivor_count(ctx: commands.Context) -> None:
        dm = await _owner_dm(bot, ctx)
        if dm is None:
            return
        rows = _iter_survivors(user_data)
        known_time = sum(1 for _uid, record in rows if _registration_ts(record) is not None)
        legacy = len(rows) - known_time
        await dm.send(
            "🧟 **ABADDON 가입 생존자 현황**\n"
            f"전체 가입 생존자: **{len(rows):,}명**\n"
            f"v18.2.1 이후 가입일 확인 가능: **{known_time:,}명**\n"
            f"기존 가입자(가입일 미기록): **{legacy:,}명**"
        )
        await _ack(ctx)

    @bot.command(
        name="생존자명단",
        aliases=["가입생존자명단", "survivorlist", "survivorroster"],
        hidden=True,
        help="[봇 소유자 전용] 가입 생존자 명단을 페이지별로 DM 전송합니다.",
    )
    async def survivor_roster(ctx: commands.Context, 페이지: int = 1) -> None:
        dm = await _owner_dm(bot, ctx)
        if dm is None:
            return
        rows = _iter_survivors(user_data)
        pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(max(1, _safe_int(페이지, 1)), pages)
        start = (page - 1) * PAGE_SIZE
        chunk = rows[start:start + PAGE_SIZE]
        embed = discord.Embed(title="🧟 ABADDON 가입 생존자 명단", color=0x7C4DFF)
        embed.description = f"총 **{len(rows):,}명** · 페이지 **{page}/{pages}** · 제작자 전용 DM"
        if not chunk:
            embed.add_field(name="명단", value="아직 가입한 생존자가 없습니다.", inline=False)
        else:
            lines: List[str] = []
            for index, (uid, record) in enumerate(chunk, start=start + 1):
                name = _display_name(bot, uid)[:32]
                level = max(1, _safe_int(record.get("level"), 1))
                ts = _registration_ts(record)
                reg = _registration(record)
                when = f"<t:{ts}:d>" if ts else "기존 가입자"
                guild_name = str(reg.get("guild_name") or "")[:24]
                guild_text = f" · {guild_name}" if guild_name and guild_name != "DM" else ""
                lines.append(f"`{index:>3}.` **{name}** · Lv.{level} · `{uid}` · {when}{guild_text}")
            # Split conservatively to stay under Discord field limits.
            current: List[str] = []
            length = 0
            part = 1
            for line in lines:
                if current and length + len(line) + 1 > 980:
                    embed.add_field(name="명단" if part == 1 else f"명단 {part}", value="\n".join(current), inline=False)
                    current, length, part = [], 0, part + 1
                current.append(line)
                length += len(line) + 1
            if current:
                embed.add_field(name="명단" if part == 1 else f"명단 {part}", value="\n".join(current), inline=False)
        embed.set_footer(text="다음 페이지: !생존자명단 2 · 상세 검색: !생존자검색 @유저")
        await dm.send(embed=embed)
        await _ack(ctx)

    @bot.command(
        name="생존자검색",
        aliases=["가입생존자검색", "survivorsearch", "survivorlookup"],
        hidden=True,
        help="[봇 소유자 전용] 가입 생존자를 멘션/ID/이름으로 검색합니다.",
    )
    async def survivor_search(ctx: commands.Context, *, 대상: str = "") -> None:
        dm = await _owner_dm(bot, ctx)
        if dm is None:
            return
        query = str(대상 or "").strip()
        if not query:
            await dm.send("사용법: `!생존자검색 @유저` · `!생존자검색 사용자ID` · `!생존자검색 이름`")
            await _ack(ctx)
            return
        direct_id = _extract_id(query)
        ids = [direct_id] if direct_id is not None else _find_by_name(bot, user_data, query)
        ids = [uid for uid in ids if uid is not None and (str(uid) in user_data or uid in user_data)]
        if not ids:
            await dm.send(f"🔎 `{query[:80]}`에 해당하는 가입 생존자를 찾지 못했습니다.")
            await _ack(ctx)
            return
        if len(ids) > 1:
            lines = [f"• **{_display_name(bot, uid)[:32]}** · `{uid}`" for uid in ids[:15]]
            await dm.send("🔎 이름이 같은/비슷한 가입자가 여러 명입니다. ID로 다시 검색해주세요.\n" + "\n".join(lines))
            await _ack(ctx)
            return
        uid = int(ids[0])
        record = user_data.get(str(uid), user_data.get(uid, {}))
        if not isinstance(record, Mapping):
            await dm.send("❌ 가입 데이터 형식을 읽지 못했습니다.")
            return
        reg = _registration(record)
        ts = _registration_ts(record)
        embed = discord.Embed(title=f"🧟 생존자 조회 · {_display_name(bot, uid)[:80]}", color=0x2ECC71)
        embed.add_field(name="Discord ID", value=f"`{uid}`", inline=False)
        embed.add_field(name="기본 상태", value=f"Lv. **{max(1, _safe_int(record.get('level'), 1))}** · 칭호 **{str(record.get('title') or '신입 생존자')[:60]}**", inline=False)
        embed.add_field(name="가입 시각", value=(f"<t:{ts}:f> · <t:{ts}:R>" if ts else "기존 가입자 · 과거 버전에는 가입 시각을 기록하지 않았습니다."), inline=False)
        guild_id = str(reg.get("guild_id") or "").strip()
        guild_name = str(reg.get("guild_name") or "").strip()
        if guild_id or guild_name:
            embed.add_field(name="최초 가입 위치", value=f"{guild_name or '알 수 없음'} · `{guild_id or '-'}`", inline=False)
        else:
            embed.add_field(name="최초 가입 위치", value="기존 가입자 · 과거 버전에는 최초 가입 서버를 기록하지 않았습니다.", inline=False)
        embed.set_footer(text="개인 메시지 내용/명령 입력값은 표시하거나 저장하지 않습니다.")
        await dm.send(embed=embed)
        await _ack(ctx)

    @bot.command(
        name="1821검수",
        aliases=["v1821audit", "1821audit"],
        hidden=True,
        help="[봇 소유자 전용] v18.2.1 생존자 명단/운영 UI 차단 상태를 검사합니다.",
    )
    async def audit_1821(ctx: commands.Context) -> None:
        if not await _private_owner(bot, ctx.author):
            return
        from apocalypse_bot.commands import v1803_contextual_ui as contextual
        checks = [
            ("생존자명단", bot.get_command("생존자명단") is not None),
            ("생존자수", bot.get_command("생존자수") is not None),
            ("생존자검색", bot.get_command("생존자검색") is not None),
            ("서버사용로그 길드 UI 차단", contextual._blocked("서버사용로그", "guild")),
            ("서버사용통계 길드 UI 차단", contextual._blocked("서버사용통계", "guild")),
            ("오해 유발 길드사용로그 별칭 제거", bot.all_commands.get("길드사용로그") is None),
            ("오해 유발 길드사용통계 별칭 제거", bot.all_commands.get("길드사용통계") is None),
            ("도박정보 보존", bot.get_command("도박정보") is not None),
        ]
        await ctx.send(
            f"🧪 **ABADDON v{VERSION} 핫픽스 검수**\n"
            + "\n".join(("✅" if ok else "❌") + f" {name}" for name, ok in checks)
            + f"\n가입 생존자: **{len(_iter_survivors(user_data)):,}명**"
        )

    patch_cmd = bot.get_command("패치노트")
    if patch_cmd is not None:
        async def patch_v1821(ctx: commands.Context) -> None:
            embed = discord.Embed(
                title="📜 ABADDON v18.2.1 · OWNER SURVIVOR HOTFIX",
                description="제작자 전용 가입 생존자 관리와 운영 명령 추천 UI 오분류를 수정했습니다.",
                color=0x7C4DFF,
            )
            embed.add_field(name="🧟 제작자 전용", value="`!생존자명단 [페이지]` · `!생존자수` · `!생존자검색 @유저/ID/이름`", inline=False)
            embed.add_field(name="🧭 추천 UI", value="`!서버사용로그` · `!서버사용통계` 등 운영 명령 뒤에 길드·파티·연합 UI가 붙지 않도록 차단했습니다.", inline=False)
            embed.add_field(name="📝 가입 기록", value="신규 가입부터 가입 시각과 최초 가입 서버를 저장합니다. 기존 가입자는 그대로 보존하며 `기존 가입자`로 표시합니다.", inline=False)
            embed.add_field(name="🎲 도박", value="카지노/일반 도박 분리는 그대로 유지했습니다. `!도박정보`와 `/도박` 그룹은 보존하며 prefix `!도박`은 이번 패치에서 변경하지 않았습니다.", inline=False)
            embed.add_field(name="🧪 검수", value="`!1821검수` · `!봇검수 상세`", inline=False)
            embed.set_footer(text="기존 유저 데이터 삭제 0건 · /var/data 저장 구조 유지")
            await ctx.send(embed=embed)
        patch_cmd.callback = patch_v1821
        patch_cmd.help = "ABADDON v18.2.1 제작자 생존자 관리/운영 UI 핫픽스 최신 패치노트입니다."
        patch_cmd.description = patch_cmd.help

    # Keep the public command catalog coherent even though these owner commands
    # are hidden. This also reclassifies the v18.1.5 commands after alias cleanup.
    try:
        from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as hub
        entries = hub._build_registry(bot)
        setattr(bot, "v1630_command_entries", entries)
        setattr(bot, "v1630_command_index", {e.qualified_name: e for e in entries})
    except Exception as exc:
        print(f"[ABADDON v{VERSION} catalog refresh warning] {type(exc).__name__}: {exc}", flush=True)

    bot._abaddon_v1821_registered = True
    bot.abaddon_version = VERSION
    print(f"[ABADDON v{VERSION}] owner survivor registry + contextual owner UI hotfix registered", flush=True)
