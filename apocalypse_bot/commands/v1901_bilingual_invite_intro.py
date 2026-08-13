from __future__ import annotations

"""ABADDON v19.0.1 bilingual invite / server-join introduction.

This patch deliberately stays on the v19.0.1 code line. It only adds a
Korean + English first-introduction surface and does not change game data,
balance, economy, or the v19.0.1 presence rotation hotfix.
"""

from typing import Optional

import discord
from discord.ext import commands

VERSION = "19.0.1"
SUPPORT_USER = "jjonga0022"
SUPPORT_INVITE = "https://discord.gg/FN2tX7TVMz"
SITE_URL = "https://san01446-ux.github.io/abaddon-policy/"


def _can_send(channel: discord.abc.GuildChannel, me: discord.Member) -> bool:
    if not isinstance(channel, discord.TextChannel):
        return False
    perms = channel.permissions_for(me)
    return bool(perms.view_channel and perms.send_messages and perms.embed_links)


def _pick_intro_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    me = guild.me
    if me is None:
        return None

    if guild.system_channel is not None and _can_send(guild.system_channel, me):
        return guild.system_channel

    preferred_names = (
        "general", "welcome", "chat", "lobby",
        "일반", "환영", "채팅", "로비", "공지",
    )
    for name in preferred_names:
        for channel in guild.text_channels:
            if channel.name.lower() == name.lower() and _can_send(channel, me):
                return channel

    for channel in guild.text_channels:
        if _can_send(channel, me):
            return channel
    return None


def _bilingual_intro_embed(guild: Optional[discord.Guild] = None) -> discord.Embed:
    server_name = guild.name if guild is not None else "Discord server"
    embed = discord.Embed(
        title="☣️ ABADDON · 종말 생존 RPG / Apocalypse Survival RPG",
        description=(
            f"**{server_name}**에 ABADDON을 추가해 주셔서 감사합니다!\n"
            "ABADDON은 전투·채집·성장·월드보스·길드·경제·이벤트·서버 관리까지 이어지는 "
            "한국어/영어 Discord 생존 RPG입니다.\n\n"
            f"Thank you for inviting **ABADDON** to **{server_name}**!\n"
            "ABADDON is a Korean/English Discord survival RPG with combat, gathering, progression, "
            "world bosses, guilds, economy, events, community tools, moderation, automation and more."
        ),
        color=0x8B5CF6,
    )
    embed.add_field(
        name="🇰🇷 한국어 빠른 시작",
        value=(
            "`!명령어` — 전체 기능 메뉴\n"
            "`!첫10분` — 초보자 빠른 시작\n"
            "`!기능찾기 <검색어>` — 명령어를 몰라도 기능 검색\n"
            "`!디스코드센터` — Discord 연동/서버 기능"
        ),
        inline=False,
    )
    embed.add_field(
        name="🇺🇸 English Quick Start",
        value=(
            "`!help` or `!commands` — English command guide\n"
            "`!first10` — quick newcomer guide\n"
            "`!featurefinder <keyword>` — find features without memorizing commands\n"
            "`!botintro` — show this introduction again"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎮 주요 기능 / Main Features",
        value=(
            "스토리 · 전투 · 던전 · 월드보스 · 장비 · 채집 · 길드 · 경제 · 미니게임 · "
            "투표 · 일정 · 티켓 · AutoMod · 서버 자동화\n"
            "Story · Combat · Dungeons · World Bosses · Equipment · Gathering · Guilds · Economy · "
            "Mini-games · Polls · Events · Tickets · AutoMod · Server Automation"
        ),
        inline=False,
    )
    embed.add_field(
        name="🛟 문의 / Support",
        value=(
            f"공식 홈페이지 / Official website: {SITE_URL}\n"
            f"지원 서버 / Support server: {SUPPORT_INVITE}\n"
            f"Discord DM: **{SUPPORT_USER}**"
        ),
        inline=False,
    )
    embed.set_footer(text=f"ABADDON v{VERSION} · 한국어 / English · !명령어 / !help")
    return embed


def register_v1901_bilingual_invite_intro(bot: commands.Bot) -> None:
    if getattr(bot, "_abaddon_v1901_bilingual_invite_intro", False):
        return
    bot._abaddon_v1901_bilingual_invite_intro = True

    async def on_guild_join_bilingual_intro(guild: discord.Guild) -> None:
        try:
            channel = _pick_intro_channel(guild)
            if channel is None:
                print(
                    f"[ABADDON v{VERSION}] bilingual invite intro skipped: no writable text channel · guild={guild.id}",
                    flush=True,
                )
                return
            await channel.send(embed=_bilingual_intro_embed(guild))
            print(
                f"[ABADDON v{VERSION}] bilingual invite intro sent · guild={guild.id} · channel={channel.id}",
                flush=True,
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(
                f"[ABADDON v{VERSION}] bilingual invite intro send warning · guild={guild.id} · "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[ABADDON v{VERSION}] bilingual invite intro unexpected warning · guild={guild.id} · "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    bot.add_listener(on_guild_join_bilingual_intro, "on_guild_join")

    # This module loads last so !봇소개 always shows both Korean and English
    # together, regardless of the user's previously selected locale.
    intro = bot.get_command("봇소개")
    if intro is not None:
        async def bilingual_bot_intro(ctx: commands.Context) -> None:
            await ctx.send(embed=_bilingual_intro_embed(ctx.guild))

        intro.callback = bilingual_bot_intro
        intro.help = "ABADDON의 한국어/영어 통합 소개와 빠른 시작을 표시합니다."
        intro.description = intro.help

    # English aliases remain available, but intentionally show the exact same
    # bilingual card so neither language disappears from the first impression.
    @bot.command(
        name="englishintro",
        aliases=["botintro", "aboutabaddon"],
        help="Show ABADDON's Korean / English introduction and quick-start guide.",
    )
    async def bilingual_intro_command(ctx: commands.Context) -> None:
        await ctx.send(embed=_bilingual_intro_embed(ctx.guild))

    print(f"[ABADDON v{VERSION}] bilingual invite introduction patch active", flush=True)
