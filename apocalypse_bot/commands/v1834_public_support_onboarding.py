from __future__ import annotations

"""ABADDON v18.3.4 public support + newcomer/server diagnostics polish.

Goals:
- keep the public Discord presence rotating every 30 seconds (implemented in core.bot)
  and expose the direct support contact in the rotation;
- make the support contact obvious in bot info/help without exposing secrets;
- give newcomers a short first-10-minutes path instead of a wall of commands;
- provide a read-only, server-admin-friendly installation diagnostic;
- keep Korean/English help registries aligned with the live command tree.
"""

from typing import Any, Dict, List, Tuple

import discord
from discord.ext import commands

VERSION = "18.3.4"
SUPPORT_USERNAME = "jjonga0022"


def _locale(bot: commands.Bot, ctx: commands.Context) -> str:
    try:
        from apocalypse_bot.commands import v1000_global_survivor as global_mod
        root = global_mod._RUNTIME.get("root", {})
        return global_mod._user_locale(root, int(ctx.author.id), int(ctx.guild.id if ctx.guild else 0))
    except Exception:
        return "ko"


def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


async def _is_owner(bot: commands.Bot, user: discord.abc.User) -> bool:
    try:
        return bool(await bot.is_owner(user))
    except Exception:
        return False


def _registered(user_data: Dict[str, Any], user_id: int) -> bool:
    return isinstance(user_data.get(str(user_id)), dict)


def _bot_permissions(ctx: commands.Context) -> discord.Permissions | None:
    try:
        if ctx.guild is None or ctx.channel is None or ctx.guild.me is None:
            return None
        return ctx.channel.permissions_for(ctx.guild.me)
    except Exception:
        return None


def register_v1834_public_support_onboarding(
    bot: commands.Bot,
    user_data: Dict[str, Any],
) -> None:
    if getattr(bot, "_abaddon_v1834_registered", False):
        return
    bot._abaddon_v1834_registered = True
    bot.abaddon_version = VERSION
    bot.abaddon_support_username = SUPPORT_USERNAME

    @bot.command(
        name="첫10분",
        aliases=["첫10분가이드", "10분가이드", "first10", "first10min", "quickstart10"],
        help="처음 가입한 생존자가 10분 안에 핵심 플레이 흐름을 익히는 짧은 가이드입니다.",
    )
    async def first_ten_minutes(ctx: commands.Context) -> None:
        loc = _locale(bot, ctx)
        joined = _registered(user_data, int(ctx.author.id))
        if loc == "en":
            title = "🌱 ABADDON · Your First 10 Minutes"
            desc = "You only need these steps. **Do not try to learn every command at once.**"
            rows = [
                ("1️⃣ Register", "✅ Already registered" if joined else "`!register survivor` or `!가입 생존자`"),
                ("2️⃣ Claim your start", "`!attendance` · then `!today` to see today's easy rewards"),
                ("3️⃣ Gather something", "Open `!commands` → **Play → Life/Gathering**, or try a simple gathering feature"),
                ("4️⃣ Fight once", "Open `!commands` → **Play → Combat** and start with an easy encounter"),
                ("5️⃣ Explore freely", "Use `!commands`. Pick only **one category → one feature group → one feature**."),
            ]
            support = f"If something breaks, use `!supportcontact` or DM **`{SUPPORT_USERNAME}`** with a screenshot/error ID."
            footer = "ABADDON v18.3.4 · simple start · no need to memorize 1,000+ commands"
        else:
            title = "🌱 ABADDON · 처음 10분"
            desc = "처음부터 모든 기능을 볼 필요 없습니다. **아래 5개만 순서대로 해보세요.**"
            rows = [
                ("1️⃣ 생존자 등록", "✅ 이미 가입되어 있습니다." if joined else "`!가입 생존자`"),
                ("2️⃣ 시작 보상", "`!출석` → `!오늘할일`로 지금 받을 수 있는 보상 확인"),
                ("3️⃣ 생활 한 번", "`!명령어` → **플레이 → 생활/채집**에서 마음에 드는 기능 하나 실행"),
                ("4️⃣ 전투 한 번", "`!명령어` → **플레이 → 전투**에서 쉬운 전투부터 시작"),
                ("5️⃣ 이제 자유롭게", "`!명령어`에서 **큰 카테고리 하나 → 기능군 하나 → 기능 하나**만 골라서 플레이"),
            ]
            support = f"막히거나 오류가 나면 `!문의처` 또는 Discord DM **`{SUPPORT_USERNAME}`** · 가능하면 오류 화면/사건 번호를 같이 보내주세요."
            footer = "ABADDON v18.3.4 · 처음부터 1,000개 넘는 명령을 외울 필요 없습니다"

        embed = discord.Embed(title=title, description=desc, color=0x57F287)
        for name, value in rows:
            embed.add_field(name=name, value=value, inline=False)
        embed.add_field(name=_t(loc, "🛟 도움이 필요하면", "🛟 Need help?"), value=support, inline=False)
        embed.set_footer(text=footer)
        await ctx.send(embed=embed)

    @bot.command(
        name="서버진단",
        aliases=["설치진단", "serverdiag", "serverdiagnostic", "installdiag"],
        help="현재 서버에서 ABADDON의 메시지·임베드·파일·UI·슬래시 준비 상태를 읽기 전용으로 점검합니다.",
    )
    async def server_diagnostic(ctx: commands.Context) -> None:
        loc = _locale(bot, ctx)
        if ctx.guild is None:
            await ctx.send(_t(loc, "⚠️ `!서버진단`은 서버 채널에서 사용해주세요.", "⚠️ `!serverdiag` must be used in a server channel."))
            return

        owner = await _is_owner(bot, ctx.author)
        perms_author = getattr(ctx.author, "guild_permissions", None)
        allowed = bool(owner or (perms_author and (perms_author.administrator or perms_author.manage_guild)))
        if not allowed:
            await ctx.send(_t(loc, "⛔ 서버 관리자 또는 ABADDON 제작자만 서버 진단을 실행할 수 있습니다.", "⛔ Server managers or the ABADDON owner can run this diagnostic."))
            return

        perms = _bot_permissions(ctx)
        critical_specs: List[Tuple[str, str]] = [
            ("view_channel", _t(loc, "채널 보기", "View Channel")),
            ("send_messages", _t(loc, "메시지 보내기", "Send Messages")),
            ("embed_links", _t(loc, "임베드 링크", "Embed Links")),
            ("read_message_history", _t(loc, "메시지 기록 보기", "Read Message History")),
        ]
        optional_specs: List[Tuple[str, str]] = [
            ("attach_files", _t(loc, "파일 첨부", "Attach Files")),
            ("add_reactions", _t(loc, "반응 추가", "Add Reactions")),
            ("use_external_emojis", _t(loc, "외부 이모지", "External Emojis")),
            ("manage_messages", _t(loc, "메시지 관리(운영 기능)", "Manage Messages (ops)")),
            ("manage_roles", _t(loc, "역할 관리(서버 운영 기능)", "Manage Roles (server ops)")),
            ("manage_channels", _t(loc, "채널 관리(문의/리뉴얼)", "Manage Channels (tickets/renewal)")),
        ]

        def has(name: str) -> bool:
            return bool(perms and getattr(perms, name, False))

        critical_ok = all(has(name) for name, _ in critical_specs)
        command_hub_ok = bot.get_command("명령어") is not None and bot.get_command("버튼") is not None
        persistent_ko = int(getattr(bot, "v1831_persistent_view_count", 0) or 0)
        persistent_en = int(getattr(bot, "v1832_persistent_view_count", 0) or 0)
        slash_total = sum(1 for _ in bot.tree.walk_commands())
        slash_status = str(getattr(bot, "_abaddon_slash_sync_status", "unknown") or "unknown")
        latency = max(0, round(float(getattr(bot, "latency", 0.0) or 0.0) * 1000))

        embed = discord.Embed(
            title=_t(loc, "🩺 ABADDON 서버 설치 진단", "🩺 ABADDON Server Diagnostic"),
            description=_t(loc, "데이터를 변경하지 않고 **이 채널에서 실제 사용 가능한 핵심 권한과 UI 상태**만 확인합니다.", "Read-only check of the permissions and UI state actually available in this channel."),
            color=0x57F287 if critical_ok and command_hub_ok else 0xFEE75C,
        )
        embed.add_field(
            name=_t(loc, "✅ 핵심 권한", "✅ Critical permissions"),
            value="\n".join(f"{'✅' if has(key) else '❌'} {label}" for key, label in critical_specs),
            inline=True,
        )
        embed.add_field(
            name=_t(loc, "🧰 확장 기능 권한", "🧰 Optional/ops permissions"),
            value="\n".join(f"{'✅' if has(key) else '▫️'} {label}" for key, label in optional_specs),
            inline=True,
        )
        embed.add_field(
            name=_t(loc, "🧭 명령/UI", "🧭 Commands/UI"),
            value=_t(
                loc,
                f"명령센터 **{'정상' if command_hub_ok else '확인 필요'}**\n영구 View KO **{persistent_ko}** · EN **{persistent_en}**\n슬래시 **{slash_total}개** · sync `{slash_status}`\nGateway **{latency}ms**",
                f"Command hub **{'ready' if command_hub_ok else 'check needed'}**\nPersistent views KO **{persistent_ko}** · EN **{persistent_en}**\nSlash **{slash_total}** · sync `{slash_status}`\nGateway **{latency}ms**",
            ),
            inline=False,
        )
        if not critical_ok:
            missing = [label for key, label in critical_specs if not has(key)]
            embed.add_field(name=_t(loc, "🚨 먼저 고칠 것", "🚨 Fix first"), value=" · ".join(missing), inline=False)
        else:
            embed.add_field(name=_t(loc, "🎯 결론", "🎯 Result"), value=_t(loc, "이 채널에서 일반 명령·임베드·핵심 버튼 UI를 사용할 기본 조건이 갖춰져 있습니다.", "This channel has the base permissions needed for normal commands, embeds, and core button UI."), inline=False)
        embed.add_field(name=_t(loc, "🛟 장애 문의", "🛟 Outage support"), value=f"`!문의처` / `!supportcontact` · Discord DM **`{SUPPORT_USERNAME}`**", inline=False)
        embed.set_footer(text=_t(loc, "확장 권한은 해당 서버관리 기능을 쓸 때만 필요합니다.", "Optional permissions are only needed for their related server-management features."))
        await ctx.send(embed=embed)

    # Final bot-info surface: overwrite the old callback after all previous language
    # layers have loaded so both Korean and English users see the same current info.
    intro = bot.get_command("봇소개")
    if intro is not None:
        previous = intro.callback

        async def v1834_bot_info(ctx: commands.Context) -> None:
            loc = _locale(bot, ctx)
            if loc == "en":
                embed = discord.Embed(
                    title="🛰️ ABADDON · Apocalypse Survival RPG",
                    description="A persistent Discord survival world with story, combat, gathering, crafting, economy, guilds, casino/gambling, living-world events and server tools.",
                    color=0xC8AA62,
                )
                fields = [
                    ("🌱 Easy start", "`!first10` → `!today` → `!commands`. Pick one category at a time."),
                    ("🧭 Live command menu", "Korean and English menus rebuild from the commands that are actually registered, keeping new features discoverable."),
                    ("🛡️ Reliability", "Persistent core navigation · automatic owner error DM · SQLite/backup protection · server diagnostics"),
                    ("🛟 Outage / bug support", f"Use `!supportcontact` or send a Discord DM to **`{SUPPORT_USERNAME}`**. Include a screenshot or incident ID when possible."),
                ]
            else:
                embed = discord.Embed(
                    title="🛰️ ABADDON · 종말 생존 RPG",
                    description="스토리·전투·채집·제작·경제·길드·카지노/도박·살아있는 세계 이벤트·서버 운영까지 하나로 이어지는 Discord 생존 RPG입니다.",
                    color=0xC8AA62,
                )
                fields = [
                    ("🌱 쉬운 시작", "`!첫10분` → `!오늘할일` → `!명령어` · 한 번에 카테고리 하나만 골라서 플레이하면 됩니다."),
                    ("🧭 실시간 명령 메뉴", "실제로 등록된 명령을 기준으로 한·영 카테고리를 다시 읽어 새 기능도 계속 메뉴 아래에 묶습니다."),
                    ("🛡️ 안정화", "핵심 영구 버튼 · 자동 오류 DM · SQLite/백업 보호 · 서버 설치 진단"),
                    ("🛟 장애·버그 문의", f"`!문의처` 또는 Discord DM **`{SUPPORT_USERNAME}`** · 오류 화면/사건 번호가 있으면 함께 보내주세요."),
                ]
            for name, value in fields:
                embed.add_field(name=name, value=value, inline=False)
            embed.set_footer(text=f"ABADDON v{VERSION} · status rotates every 30s · support @{SUPPORT_USERNAME}")
            await ctx.send(embed=embed)

        intro.callback = v1834_bot_info
        intro.help = "ABADDON 최신 기능, 쉬운 시작, 안정화 상태와 장애 문의 연락처를 확인합니다."
        intro.description = intro.help
        intro.extras = dict(getattr(intro, "extras", {}) or {})
        intro.extras["v1834_previous_callback"] = previous

    @bot.command(
        name="1834검수",
        aliases=["1834audit", "publicsupportaudit"],
        hidden=True,
        help="[봇 소유자 전용] v18.3.4 공개 상태/문의/첫10분/서버진단 연결을 검사합니다.",
    )
    async def audit_1834(ctx: commands.Context) -> None:
        if not await _is_owner(bot, ctx.author):
            return
        activity_name = str(getattr(getattr(bot, "activity", None), "name", "") or "")
        checks = [
            ("첫10분", bot.get_command("첫10분") is not None),
            ("서버진단", bot.get_command("서버진단") is not None),
            ("문의처", bot.get_command("문의처") is not None),
            ("봇소개", bot.get_command("봇소개") is not None),
            ("문의 사용자명", getattr(bot, "abaddon_support_username", "") == SUPPORT_USERNAME),
            ("한글 영구 명령 허브", bot.get_command("명령어") is not None),
            ("영문 영구 명령 허브", bot.get_command("help") is not None),
        ]
        embed = discord.Embed(title=f"🧪 ABADDON v{VERSION} PUBLIC SUPPORT 검수", color=0x57F287 if all(x[1] for x in checks) else 0xFEE75C)
        embed.description = "\n".join(f"{'✅' if ok else '❌'} {name}" for name, ok in checks)
        embed.add_field(name="현재 Presence", value=activity_name or "아직 첫 순환 전", inline=False)
        embed.add_field(name="장애 문의", value=f"Discord DM `{SUPPORT_USERNAME}`", inline=False)
        embed.set_footer(text="상태 메시지는 core.bot에서 30초 주기로 순차 회전")
        await ctx.send(embed=embed)

    # Update the current patch note surface last.
    patch = bot.get_command("패치노트")
    if patch is not None:
        previous_patch = patch.callback

        async def patch_v1834(ctx: commands.Context, *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            loc = _locale(bot, ctx)
            embed = discord.Embed(title="📡 ABADDON v18.3.4 — PUBLIC SUPPORT & ONBOARDING", color=0x5865F2)
            embed.description = _t(loc, "상태 메시지·장애 문의·초보 시작·서버 설치 점검을 한 번에 정리한 공개 운영 패치입니다.", "Public operations update for rotating presence, direct support, newcomer onboarding and server diagnostics.")
            embed.add_field(name=_t(loc, "🔄 30초 상태 순환", "🔄 30s Presence Rotation"), value=_t(loc, f"기존 기능 안내 + `장애 문의 DM · {SUPPORT_USERNAME}`를 랜덤이 아닌 순서대로 자동 순환", f"Gameplay hints plus `Bug support DM · {SUPPORT_USERNAME}` rotate sequentially instead of randomly."), inline=False)
            embed.add_field(name=_t(loc, "🌱 처음 10분", "🌱 First 10 Minutes"), value="`!첫10분` / `!first10`", inline=False)
            embed.add_field(name=_t(loc, "🩺 서버 진단", "🩺 Server Diagnostic"), value="`!서버진단` / `!serverdiag`", inline=False)
            embed.add_field(name=_t(loc, "🛟 장애 문의", "🛟 Outage Support"), value=f"`!문의처` · Discord DM **`{SUPPORT_USERNAME}`**", inline=False)
            embed.add_field(name=_t(loc, "🌐 홈페이지", "🌐 Website"), value=_t(loc, "공식 홈페이지 배포본도 같은 패치 버전 기준으로 동기화", "Official website package synchronized to the same release."), inline=False)
            embed.set_footer(text="유저 게임 데이터/경제 데이터 변경 없음 · /var/data 유지")
            await ctx.send(embed=embed)

        patch.callback = patch_v1834
        patch.help = "ABADDON v18.3.4 상태/문의/초보/서버진단 최신 패치노트입니다."
        patch.description = patch.help
        patch.extras = dict(getattr(patch, "extras", {}) or {})
        patch.extras["v1834_previous_callback"] = previous_patch

    # New commands are automatically re-read each time the v18.3.1/3.2 menus open.
    # Refresh cached metadata as well so static status panels see them immediately.
    try:
        from apocalypse_bot.commands.v1831_persistent_command_hub import _refresh_registry
        _refresh_registry(bot)
    except Exception:
        pass
    try:
        from apocalypse_bot.commands.v1832_bilingual_persistent_hub import _sync_registry
        _sync_registry(bot)
    except Exception:
        pass

    print(
        f"[ABADDON v{VERSION}] public support/onboarding ready · presence=30s-sequential "
        f"support={SUPPORT_USERNAME} first10=True serverdiag=True",
        flush=True,
    )
