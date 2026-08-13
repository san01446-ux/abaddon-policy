from __future__ import annotations

import discord
from discord.ext import commands

VERSION = "6.3.5c"


def register_v635_casino_base(bot: commands.Bot) -> None:
    patch_notes = bot.get_command("패치노트")
    if patch_notes is not None:
        async def v635_patch_notes(ctx: commands.Context) -> None:
            embed = discord.Embed(
                title="🎰🏕️ ABADDON v6.3.5c — 홈페이지 표시 핫픽스",
                description=(
                    "무기 70종·보물 20종 이미지를 전면 리뉴얼하고, "
                    "카지노 결과 이미지는 제거해 더 깔끔한 결과 UI로 정리했습니다."
                ),
                color=discord.Color.dark_purple(),
            )
            embed.add_field(
                name="🖼️ 무기·보물 비주얼 리뉴얼",
                value=(
                    "• 장비 70종 카드 이미지를 더미 실루엣에서 고해상도 카드형 비주얼로 교체\n"
                    "• 보물 20종 감정 이미지를 어두운 유물 카드 스타일로 재정비\n"
                    "• 기존 `!장비`·제작·감정·상세 카드 출력 구조는 유지\n"
                    "• 공식 홈페이지 장비/보물 미리보기 이미지도 함께 갱신"
                ),
                inline=False,
            )
            embed.add_field(
                name="🎰 카지노 연출 정리",
                value=(
                    "• 카지노 결과 임베드의 첨부 이미지를 전부 제거해 텍스트/임베드 중심으로 정리\n"
                    "• 손익, 판정, 배팅 결과 계산 로직은 유지\n"
                    "• 공식 홈페이지 메인에서도 카지노 이미지 카드를 제거하고 설명 중심으로 수정"
                ),
                inline=False,
            )
            embed.add_field(
                name="🏕️ 고난도 기지 업그레이드",
                value=(
                    "• Lv.1 야영지부터 Lv.5 요새급 기지까지 단계별 외형 적용\n"
                    "• 상위 단계일수록 나무·광석·고철·식량 요구량 대폭 증가\n"
                    "• 강화 즉시 완료 방식 제거: 30분·2시간·8시간·24시간 공사 시간 적용\n"
                    "• 건설·진행 중·성공·자원 부족·수확 결과별 전용 이미지 적용"
                ),
                inline=False,
            )
            embed.add_field(
                name="⚔️ 던전 전투력 판정 핫픽스",
                value=(
                    "• 전투력이 적의 2배 이상이면 확정 승리\n"
                    "• 우세 전투력에서도 발생하던 고정 20% 패배 구간 제거\n"
                    "• 골절·중독·감염 패널티가 전투력 우세를 과도하게 무효화하지 않도록 제한\n"
                    "• 전투 시작 메시지에 최종 승리 확률 표시"
                ),
                inline=False,
            )
            embed.add_field(
                name="🌐 홈페이지 표시 핫픽스",
                value=(
                    "• 생활 콘텐츠 가운데 광산 대표 이미지를 실제 채굴 장면으로 교체\n"
                    "• 메인 제목과 설명 문구를 짧고 읽기 쉽게 정리\n"
                    "• 홈페이지 버전·업데이트 기록을 v6.3.5c로 동기화"
                ),
                inline=False,
            )
            embed.add_field(
                name="📚 안내 최신화",
                value=(
                    "• `!명령어` 카지노/기지 카테고리 최신 명령어와 사용법 반영\n"
                    "• 공식 홈페이지 메인·업데이트 기록·명령어 검색을 v6.3.5c로 동기화\n"
                    "• 장비·보물·펫·생활 콘텐츠와 기존 확률·전투 규칙은 유지"
                ),
                inline=False,
            )
            embed.set_footer(text="최신 버전 v6.3.5c · 홈페이지 표시 핫픽스")
            await ctx.send(embed=embed)

        patch_notes.callback = v635_patch_notes
        patch_notes.help = "ABADDON v6.3.5c 홈페이지 표시 핫픽스와 기존 리뉴얼 내용을 확인합니다."
        patch_notes.description = patch_notes.help

    bot.v635_casino_base_version = VERSION
