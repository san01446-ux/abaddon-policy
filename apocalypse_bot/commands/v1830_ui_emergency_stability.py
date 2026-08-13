from __future__ import annotations

"""ABADDON v18.3.0 UI EMERGENCY STABILITY.

Emergency compatibility layer for discord.py 2.7.x dynamic View rebinding.

ABADDON has several stateful menus that rebuild their children in-place after a
component interaction. discord.py 2.7 detaches ``Item.view`` immediately when
``View.clear_items`` / ``View.remove_item`` is called. While an interaction
message edit is still in flight, the library's message-bound view cache can
therefore briefly point at an item whose ``view`` is None. Under REST/Cloudflare
latency this window becomes large enough for a second click to be discarded as
"View interaction referencing unknown view".

This module keeps removed ABADDON items bound only for that short in-flight
cache-rebind window. The library still removes stale dispatch keys when the
edited view is stored, so this does not make menus persistent or keep old
messages alive across process restarts.
"""

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import re

import discord
from discord.ext import commands

VERSION = "18.3.0"


def _is_abaddon_view(view: Any) -> bool:
    try:
        return str(view.__class__.__module__).startswith("apocalypse_bot.")
    except Exception:
        return False


def _view_is_dispatching(view: Any) -> bool:
    try:
        return bool(view.is_dispatching())
    except Exception:
        return False


def _remember_owner(item: Any, view: Any) -> None:
    try:
        setattr(item, "_abaddon_owner_view", view)
    except Exception:
        pass


def _owner_for_item(item: Any) -> Any:
    return getattr(item, "_abaddon_owner_view", None) or getattr(item, "owner_view", None)


def _rebind_detached(item: Any, view: Any) -> bool:
    try:
        if getattr(item, "view", None) is None:
            updater = getattr(item, "_update_view", None)
            if callable(updater):
                updater(view)
                try:
                    current = int(getattr(discord.ui.View, "_abaddon_v1830_rebind_count", 0) or 0)
                    discord.ui.View._abaddon_v1830_rebind_count = current + 1  # type: ignore[attr-defined]
                except Exception:
                    pass
                return getattr(item, "view", None) is view
    except Exception:
        return False
    return False


def _install_dynamic_view_rebind_guard() -> bool:
    View = discord.ui.View
    if getattr(View, "_abaddon_v1830_rebind_guard", False):
        return True

    original_clear = View.clear_items
    original_remove = View.remove_item

    def guarded_clear_items(self: discord.ui.View):
        # Only ABADDON's already-dispatching message views need compatibility.
        # Initial constructor rebuilds should retain discord.py's native 2.7
        # behaviour.
        keep_binding = _is_abaddon_view(self) and _view_is_dispatching(self)
        old_children = list(getattr(self, "children", []) or []) if keep_binding else []
        if keep_binding:
            for child in old_children:
                _remember_owner(child, self)
        result = original_clear(self)
        if keep_binding:
            for child in old_children:
                _rebind_detached(child, self)
        return result

    def guarded_remove_item(self: discord.ui.View, item: Any):
        keep_binding = _is_abaddon_view(self) and _view_is_dispatching(self)
        was_present = False
        if keep_binding:
            try:
                was_present = item in list(getattr(self, "children", []) or [])
            except Exception:
                was_present = False
        if keep_binding and was_present:
            _remember_owner(item, self)
        result = original_remove(self, item)
        if keep_binding and was_present:
            _rebind_detached(item, self)
        return result

    # Preserve references for diagnostics and future rollback.
    View._abaddon_v1830_original_clear_items = original_clear  # type: ignore[attr-defined]
    View._abaddon_v1830_original_remove_item = original_remove  # type: ignore[attr-defined]
    View.clear_items = guarded_clear_items  # type: ignore[assignment]
    View.remove_item = guarded_remove_item  # type: ignore[assignment]
    View._abaddon_v1830_rebind_count = 0  # type: ignore[attr-defined]
    View._abaddon_v1830_rebind_guard = True  # type: ignore[attr-defined]
    return True


def _install_view_error_fallback() -> bool:
    View = discord.ui.View
    if getattr(View, "_abaddon_v1830_error_fallback", False):
        return True
    original = View.on_error

    async def on_error(self: discord.ui.View, interaction: discord.Interaction, error: Exception, item: Any, /) -> None:
        if _is_abaddon_view(self):
            label = str(getattr(item, "label", "") or getattr(item, "placeholder", "") or item.__class__.__name__)
            custom_id = str(getattr(item, "custom_id", "") or "-")
            print(
                f"[ABADDON v{VERSION}] UI callback error · view={self.__class__.__name__} "
                f"item={label[:60]!r} custom_id={custom_id[:100]!r} "
                f"error={type(error).__name__}: {error}",
                flush=True,
            )
            try:
                notice = (
                    "⚠️ 버튼 처리 중 오류가 감지됐습니다. 같은 기능을 한 번 더 열어 시도해주세요. "
                    "오류가 반복되면 `!버그신고`로 제보할 수 있습니다."
                )
                if not interaction.response.is_done():
                    await interaction.response.send_message(notice, ephemeral=True)
                else:
                    # Some ABADDON button bridges defer immediately. If the later
                    # message edit fails, response.is_done() is already True, so
                    # use a follow-up instead of leaving the click apparently dead.
                    await interaction.followup.send(notice, ephemeral=True)
            except Exception:
                pass
        await original(self, interaction, error, item)

    View.on_error = on_error  # type: ignore[assignment]
    View._abaddon_v1830_error_fallback = True  # type: ignore[attr-defined]
    return True


def _candidate_missing(bot: commands.Bot) -> List[str]:
    try:
        from apocalypse_bot.commands import v1803_contextual_ui as ui
    except Exception:
        return ["v1803_contextual_ui import"]
    missing: List[str] = []
    for group, rows in getattr(ui, "GROUP_BUTTONS", {}).items():
        for candidate in rows:
            names = tuple(str(x) for x in getattr(candidate, "names", ()) if x)
            if names and not any(bot.get_command(name) is not None for name in names):
                missing.append(f"{group}:{'/'.join(names)}")
    for key, rows in getattr(ui, "SPECIAL_BUTTONS", {}).items():
        for candidate in rows:
            names = tuple(str(x) for x in getattr(candidate, "names", ()) if x)
            if names and not any(bot.get_command(name) is not None for name in names):
                missing.append(f"special:{key}:{'/'.join(names)}")
    return missing


def _view_store_health(bot: commands.Bot) -> Tuple[int, int, int]:
    total = dead = recoverable = 0
    try:
        store = bot._connection._view_store  # type: ignore[attr-defined]
        for mapping in list(getattr(store, "_views", {}).values()):
            for item in list(mapping.values()):
                total += 1
                if getattr(item, "view", None) is None:
                    dead += 1
                    owner = _owner_for_item(item)
                    if owner is not None and not bool(getattr(owner, "is_finished", lambda: True)()):
                        recoverable += 1
    except Exception:
        pass
    return total, dead, recoverable


def _repair_recoverable_bindings(bot: commands.Bot) -> Tuple[int, int]:
    repaired = removed = 0
    try:
        store = bot._connection._view_store  # type: ignore[attr-defined]
        views = getattr(store, "_views", {})
        for entity_id, mapping in list(views.items()):
            for key, item in list(mapping.items()):
                if getattr(item, "view", None) is not None:
                    continue
                owner = _owner_for_item(item)
                if owner is not None and not bool(getattr(owner, "is_finished", lambda: True)()):
                    if _rebind_detached(item, owner):
                        repaired += 1
                        continue
                mapping.pop(key, None)
                removed += 1
            if not mapping:
                views.pop(entity_id, None)
    except Exception:
        pass
    return repaired, removed


def _source_mutation_sites() -> List[str]:
    root = Path(__file__).resolve().parents[1] / "commands"
    this_file = Path(__file__).resolve()
    rows: List[str] = []
    for path in sorted(root.glob("*.py")):
        # Exclude this compatibility layer itself and count only actual method
        # call sites in ABADDON feature modules.
        try:
            if path.resolve() == this_file:
                continue
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        clear_count = text.count(".clear_items(")
        remove_count = text.count(".remove_item(")
        if clear_count or remove_count:
            rows.append(f"{path.name}: clear={clear_count} remove={remove_count}")
    return rows


async def _owner_only(bot: commands.Bot, ctx: commands.Context) -> bool:
    try:
        ok = bool(await bot.is_owner(ctx.author))
    except Exception:
        ok = False
    if not ok:
        try:
            await ctx.send("⛔ 이 명령은 ABADDON 제작자만 사용할 수 있습니다.")
        except Exception:
            pass
    return ok


def register_v1830_ui_emergency_stability(bot: commands.Bot) -> None:
    if getattr(bot, "_abaddon_v1830_registered", False):
        return
    bot._abaddon_v1830_registered = True
    bot.abaddon_version = VERSION

    guard_ok = _install_dynamic_view_rebind_guard()
    fallback_ok = _install_view_error_fallback()
    bot.v1830_dynamic_view_rebind_guard = guard_ok
    bot.v1830_ui_error_fallback = fallback_ok

    # Explicitly restore the short !버튼 entry point. It opens the exact same
    # current command centre as !명령어 and does not maintain a second menu.
    if bot.get_command("버튼") is None:
        @bot.command(name="버튼", aliases=["버튼메뉴", "UI열기"], hidden=True, help="최신 버튼형 전체 명령어 센터를 엽니다.")
        async def button_entry(ctx: commands.Context, *, 검색어: str = "") -> None:
            target = bot.get_command("명령어")
            if target is None:
                await ctx.send("⚠️ 명령어 센터를 찾지 못했습니다. `!버그신고 명령어 센터 누락`으로 제보해주세요.")
                return
            kwargs: Dict[str, Any] = {}
            if str(검색어 or "").strip():
                kwargs["검색어"] = str(검색어).strip()
            await ctx.invoke(target, **kwargs)

    @bot.command(
        name="1830버튼검수",
        aliases=["1830UI검수", "전체UI검수", "버튼긴급검수"],
        hidden=True,
        help="제작자 전용: 전체 버튼·드롭다운·View 캐시·슬래시 그룹 연결 상태를 검사합니다.",
    )
    async def audit_1830(ctx: commands.Context, mode: str = "") -> None:
        if not await _owner_only(bot, ctx):
            return
        missing = _candidate_missing(bot)
        total, dead, recoverable = _view_store_health(bot)
        mutation_sites = _source_mutation_sites()
        critical = (
            "명령어", "버튼", "도박정보", "카지노", "살아있는세계", "오늘의세계사건",
            "채집", "벌목", "가방", "장비", "정보", "초보생존", "솔로원정",
        )
        missing_critical = [name for name in critical if bot.get_command(name) is None]
        tree_names: List[str] = []
        try:
            tree_names = sorted(str(getattr(cmd, "name", "")) for cmd in bot.tree.get_commands())
        except Exception:
            pass
        checks = [
            ("동적 View 재바인딩 가드", bool(getattr(discord.ui.View, "_abaddon_v1830_rebind_guard", False))),
            ("UI 콜백 오류 폴백", bool(getattr(discord.ui.View, "_abaddon_v1830_error_fallback", False))),
            ("핵심 버튼 대상 명령", not missing_critical),
            ("상황형 버튼 대상 100% 연결", not missing),
            ("현재 View 캐시 dead binding 0", dead == 0),
            ("슬래시 명령 트리 존재", bool(tree_names)),
        ]
        ok = all(flag for _, flag in checks)
        embed = discord.Embed(
            title=f"🛡️ ABADDON v{VERSION} 전체 UI 긴급 검수",
            color=0x2ECC71 if ok else 0xE67E22,
        )
        embed.description = "\n".join(f"{'✅' if flag else '❌'} {name}" for name, flag in checks)
        embed.add_field(name="Discord UI 런타임", value=f"discord.py `{getattr(discord, '__version__', '?')}` · cache bindings **{total}** · dead **{dead}** · recoverable **{recoverable}**", inline=False)
        embed.add_field(
            name="동적 View 재조립 지점",
            value=(
                f"소스 **{len(mutation_sites)}개 파일** · clear/remove 안전 가드 적용 · "
                f"런타임 재바인딩 **{int(getattr(discord.ui.View, '_abaddon_v1830_rebind_count', 0) or 0)}회**"
            ),
            inline=False,
        )
        embed.add_field(name="슬래시 최상위", value=" · ".join(f"`/{x}`" for x in tree_names[:24]) or "확인 불가", inline=False)
        if str(mode).casefold() in {"상세", "detail", "full", "전체"} or not ok:
            embed.add_field(name="누락 핵심 명령", value=" · ".join(f"`!{x}`" for x in missing_critical) or "없음", inline=False)
            embed.add_field(name="누락 상황형 버튼", value="\n".join(missing[:20])[:1024] or "없음", inline=False)
            embed.add_field(name="재조립 소스", value="\n".join(mutation_sites)[:1024] or "없음", inline=False)
        embed.set_footer(text="읽기 전용 검수 · 유저 데이터 변경 없음")
        await ctx.send(embed=embed)

    @bot.command(
        name="UI캐시복구",
        aliases=["버튼캐시복구", "viewcacherepair"],
        hidden=True,
        help="제작자 전용: 현재 프로세스의 분리된 View 캐시 항목을 안전하게 재연결/정리합니다.",
    )
    async def repair_ui_cache(ctx: commands.Context) -> None:
        if not await _owner_only(bot, ctx):
            return
        before = _view_store_health(bot)
        repaired, removed = _repair_recoverable_bindings(bot)
        after = _view_store_health(bot)
        await ctx.send(
            "🧹 **UI 캐시 복구 완료**\n"
            f"전: bindings {before[0]} · dead {before[1]} → 후: bindings {after[0]} · dead {after[1]}\n"
            f"재연결 **{repaired}건** · 오래된 항목 제거 **{removed}건**"
        )

    # Advance canonical patch notes while preserving the existing command.
    patch = bot.get_command("패치노트")
    if patch is not None:
        previous = patch.callback

        async def patch_v1830(ctx: commands.Context, *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            embed = discord.Embed(title="🛡️ ABADDON v18.3.0 — UI EMERGENCY STABILITY", color=0x5865F2)
            embed.description = "버튼·드롭다운이 연속 클릭이나 REST 지연 중 `unknown view`로 끊기는 핵심 UI 레이스를 전면 보강했습니다."
            embed.add_field(name="🔧 핵심 수정", value="discord.py 2.7 동적 View 재조립 시 제거된 Item의 연결을 메시지 View 캐시가 갱신될 때까지 안전하게 유지", inline=False)
            embed.add_field(name="🧭 핵심 화면", value="`!명령어` · `!버튼` · 세계/도박/카지노 빠른 이동 · 채집센터 · 초보 생존 · 도시 공방 · 시즌/알림 UI", inline=False)
            embed.add_field(name="🧪 제작자 검수", value="`!1830버튼검수 상세` · `!UI캐시복구`", inline=False)
            embed.add_field(name="💾 데이터", value="저장 데이터 스키마 변경 없음 · `/var/data` 기존 데이터 그대로 사용", inline=False)
            await ctx.send(embed=embed)

        patch.callback = patch_v1830
        patch.help = "ABADDON v18.3.0 전체 버튼·드롭다운 긴급 안정화 최신 패치노트입니다."
        patch.description = patch.help
        patch.extras = dict(getattr(patch, "extras", {}) or {})
        patch.extras["v1830_previous_callback"] = previous

    @bot.listen("on_ready")
    async def _v1830_ready_audit() -> None:
        total, dead, recoverable = _view_store_health(bot)
        if dead:
            repaired, removed = _repair_recoverable_bindings(bot)
            total2, dead2, _ = _view_store_health(bot)
            print(
                f"[ABADDON v{VERSION}] startup UI cache repair: before_dead={dead} "
                f"recoverable={recoverable} repaired={repaired} removed={removed} after_dead={dead2} bindings={total2}",
                flush=True,
            )
        print(
            f"[ABADDON v{VERSION}] UI emergency stability ready · discord.py={getattr(discord, '__version__', '?')} "
            f"rebind_guard={bool(getattr(discord.ui.View, '_abaddon_v1830_rebind_guard', False))} bindings={total}",
            flush=True,
        )

    print(
        f"[ABADDON v{VERSION}] UI emergency stability registered: "
        f"dynamic_rebind_guard={guard_ok} error_fallback={fallback_ok} !버튼=enabled",
        flush=True,
    )
