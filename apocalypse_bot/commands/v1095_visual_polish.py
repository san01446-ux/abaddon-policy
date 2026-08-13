from __future__ import annotations

"""ABADDON v10.9.5 gameplay presentation and recovery helpers.

The module builds optional animated table media, replay timeline PNGs and a
single live board for card tables and horse races. Private hands are never read
by replay/live-board renderers.
"""

from io import BytesIO
import os
import time
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw

from apocalypse_bot.commands.v1094_card_table_images import render_session_table
from apocalypse_bot.commands.v1094_visual_core import (
    clean_text,
    draw_wrapped,
    fit_font,
    font,
    png,
    rounded,
    truncate,
)

VERSION = "11.4.0"
ANIMATED_TABLES = os.getenv("ABADDON_ANIMATED_TABLES", "1").strip().lower() not in {"0", "false", "off", "no"}

BG = (15, 14, 20)
PANEL = (41, 38, 49)
PANEL_2 = (55, 50, 65)
TEXT = (246, 243, 238)
MUTED = (190, 184, 198)
GOLD = (238, 194, 82)
GREEN = (74, 222, 151)
BLUE = (93, 168, 248)
RED = (239, 82, 103)
PURPLE = (184, 111, 248)


def _locale(value: Any) -> str:
    return "en" if str(getattr(value, "locale", getattr(value, "public_locale", "ko"))).lower().startswith("en") else "ko"


def _names(session: Any) -> Mapping[int, str]:
    value = getattr(session, "names", {})
    return value if isinstance(value, Mapping) else {}


def _current_uid(session: Any) -> int | None:
    for value in (getattr(session, "current_uid", None), getattr(getattr(session, "engine", None), "current_uid", None)):
        try:
            if value is not None:
                return int(value)
        except Exception:
            pass
    return None


def _phase(session: Any) -> str:
    for attr in ("stage_label", "stage", "street", "phase", "state"):
        value = getattr(session, attr, None)
        if value not in (None, ""):
            return clean_text(value)
    return "진행 중" if _locale(session) == "ko" else "In progress"


def _last_action(session: Any, embed: Any | None = None) -> str:
    value = clean_text(getattr(session, "last_action", ""))
    if value:
        return value
    replay = getattr(session, "replay", None)
    if isinstance(replay, Sequence) and replay:
        return clean_text(replay[-1])
    if embed is not None:
        return clean_text(getattr(embed, "description", ""))
    return ""


def _history(session: Any) -> list[str]:
    rows: list[str] = []
    replay = getattr(session, "replay", None)
    if isinstance(replay, Sequence):
        rows.extend(clean_text(row) for row in replay[-4:] if clean_text(row))
    visual = getattr(session, "_v1095_visual_history", None)
    if isinstance(visual, Sequence):
        rows.extend(clean_text(row) for row in visual[-4:] if clean_text(row))
    deduped: list[str] = []
    for row in rows:
        if row and (not deduped or deduped[-1] != row):
            deduped.append(row)
    return deduped[-4:]


def _overlay_frame(base: Image.Image, session: Any, embed: Any | None, frame_index: int) -> Image.Image:
    image = base.copy().convert("RGB")
    draw = ImageDraw.Draw(image)
    locale = _locale(session)
    current = _current_uid(session)
    name = _names(session).get(current, "ABADDON") if current is not None else ("정산 완료" if locale == "ko" else "Settled")
    phase = _phase(session)
    action = _last_action(session, embed)

    pulse = (93 + frame_index * 20, 168 + frame_index * 8, 248)
    rounded(draw, (22, 22, 1258, 116), 26, fill=(25, 23, 31), outline=pulse, width=4)
    draw.text((52, 42), "현재 차례" if locale == "ko" else "ACTIVE TURN", font=font(16, True), fill=MUTED)
    active_font = fit_font(draw, name, 480, 28, 18, bold=True)
    draw.text((52, 67), truncate(draw, name, active_font, 480), font=active_font, fill=TEXT)
    draw.text((610, 44), "단계" if locale == "ko" else "PHASE", font=font(15, True), fill=MUTED)
    draw.text((610, 70), truncate(draw, phase, font(21, True), 245), font=font(21, True), fill=GOLD)

    # A small public card token moves across the banner. It is decorative and
    # never reveals a real private card.
    token_x = 900 + frame_index * 58
    rounded(draw, (token_x, 43, token_x + 48, 100), 9, fill=(68, 42, 92), outline=PURPLE, width=3)
    draw.text((token_x + 24, 72), "A", font=font(22, True), fill=(232, 216, 255), anchor="mm")

    if action:
        draw.text((1198, 45), "최근 행동" if locale == "ko" else "LAST ACTION", font=font(14, True), fill=MUTED, anchor="ra")
        draw.text((1198, 72), truncate(draw, action, font(17, True), 290), font=font(17, True), fill=GREEN, anchor="ra")
    return image


def render_session_media(session: Any, embed: Any | None = None) -> tuple[BytesIO | None, str]:
    """Return table media and extension.

    Finished tables remain PNGs. Active tables optionally use a short three-
    frame GIF that emphasizes the active turn without exposing private cards.
    """
    base_io = render_session_table(session, embed)
    if base_io is None:
        return None, "png"
    if not ANIMATED_TABLES or bool(getattr(session, "done", False)):
        base_io.seek(0)
        return base_io, "png"
    try:
        base_io.seek(0)
        base = Image.open(base_io).convert("RGB")
        frames = [_overlay_frame(base, session, embed, index) for index in range(3)]
        out = BytesIO()
        frames[0].save(
            out,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=(180, 180, 260),
            loop=0,
            optimize=True,
        )
        out.seek(0)
        # Discord upload safety: a pathological image should fall back to PNG.
        if len(out.getbuffer()) > 7_500_000:
            base_io.seek(0)
            return base_io, "png"
        return out, "gif"
    except Exception:
        base_io.seek(0)
        return base_io, "png"


def render_replay_timeline(row: Mapping[str, Any], locale: str = "ko") -> BytesIO:
    image = Image.new("RGB", (1280, 720), BG)
    draw = ImageDraw.Draw(image)
    rounded(draw, (18, 18, 1262, 702), 30, fill=(31, 29, 38), outline=(117, 106, 134), width=4)

    game = clean_text(row.get("game", "Game"))
    result = clean_text(row.get("result", "-"))
    stake = int(row.get("stake", 0) or 0)
    title = f"게임 리플레이 · {game}" if locale == "ko" else f"Game Replay · {game}"
    draw.text((50, 36), title, font=fit_font(draw, title, 1130, 34, 22, bold=True), fill=TEXT)
    draw.text((52, 86), f"ID {row.get('id', '-')} · {'판돈' if locale == 'ko' else 'Stake'} {stake:,}", font=font(17, True), fill=GOLD)

    players = row.get("players", {})
    names = list(players.values()) if isinstance(players, Mapping) else []
    rounded(draw, (48, 126, 1232, 210), 18, fill=PANEL, outline=(85, 79, 99), width=2)
    draw.text((68, 144), "참가자" if locale == "ko" else "Players", font=font(17, True), fill=MUTED)
    draw.text((68, 172), truncate(draw, " · ".join(clean_text(name) for name in names) or "-", font(20, True), 1120), font=font(20, True), fill=TEXT)

    events = [clean_text(value) for value in list(row.get("events", [])) if clean_text(value)]
    events = events[-10:]
    draw.text((52, 236), "턴 타임라인" if locale == "ko" else "Turn Timeline", font=font(21, True), fill=BLUE)
    y = 278
    for index, event in enumerate(events or (["기록 없음"] if locale == "ko" else ["No events"]), 1):
        marker = GREEN if index == len(events) else PURPLE
        draw.ellipse((58, y + 7, 72, y + 21), fill=marker)
        if index < len(events):
            draw.line((65, y + 22, 65, y + 53), fill=(88, 82, 103), width=3)
        event_font = font(17)
        lines = draw_wrapped(draw, (88, y), event, event_font, 1110, fill=TEXT, max_lines=2, spacing=3)
        y = max(y + 43, lines + 5)
        if y > 585:
            break

    rounded(draw, (48, 602, 1232, 664), 16, fill=PANEL_2, outline=GOLD, width=2)
    draw.text((68, 620), ("결과" if locale == "ko" else "Result"), font=font(16, True), fill=MUTED)
    result_font = fit_font(draw, result, 990, 22, 16, bold=True)
    draw.text((180, 620), truncate(draw, result, result_font, 990), font=result_font, fill=GOLD)
    draw.text((1230, 681), f"ABADDON v{VERSION}", font=font(14, True), fill=PURPLE, anchor="ra")
    return png(image)


def render_live_board(
    *,
    locale: str,
    active_games: Mapping[int, Any],
    live_races: Mapping[int, Mapping[str, Any]],
    recent_races: Sequence[Mapping[str, Any]] = (),
) -> BytesIO:
    image = Image.new("RGB", (1280, 720), BG)
    draw = ImageDraw.Draw(image)
    rounded(draw, (18, 18, 1262, 702), 30, fill=(31, 29, 38), outline=(117, 106, 134), width=4)
    title = "ABADDON 실시간 게임 보드" if locale == "ko" else "ABADDON Live Game Board"
    draw.text((50, 36), title, font=font(34, True), fill=TEXT)
    draw.text((52, 84), "카드 테이블과 경마 진행 상태를 한 화면에서 확인합니다." if locale == "ko" else "Card tables and horse races in one live view.", font=font(17), fill=MUTED)

    rounded(draw, (48, 126, 622, 650), 22, fill=PANEL, outline=BLUE, width=3)
    draw.text((72, 150), f"🎴 {'진행 중 카드게임' if locale == 'ko' else 'Active Card Tables'} · {len(active_games)}", font=font(22, True), fill=BLUE)
    y = 198
    for channel_id, session in list(active_games.items())[:8]:
        kind = clean_text(getattr(session, "kind", getattr(session, "variant", session.__class__.__name__)))
        current = _current_uid(session)
        current_name = _names(session).get(current, "ABADDON") if current is not None else "-"
        players = len(getattr(session, "player_ids", []) or [])
        row = f"#{channel_id} · {kind} · {players}{'명' if locale == 'ko' else 'p'} · {current_name}"
        rounded(draw, (70, y, 600, y + 48), 13, fill=(34, 32, 41), outline=(79, 74, 91), width=1)
        draw.text((84, y + 13), truncate(draw, row, font(16, True), 500), font=font(16, True), fill=TEXT)
        y += 58
    if not active_games:
        draw.text((78, 214), "현재 진행 중인 카드게임이 없습니다." if locale == "ko" else "No active card table.", font=font(18), fill=MUTED)

    rounded(draw, (646, 126, 1232, 650), 22, fill=PANEL, outline=GOLD, width=3)
    draw.text((670, 150), f"🏇 {'실시간 경마' if locale == 'ko' else 'Live Horse Races'} · {len(live_races)}", font=font(22, True), fill=GOLD)
    y = 198
    for owner_id, state in list(live_races.items())[:6]:
        selected = clean_text(state.get("selected_name", "-"))
        leader = clean_text(state.get("leader_name", "-"))
        tick = int(state.get("tick", 0) or 0)
        row = f"{owner_id} · {'선택' if locale == 'ko' else 'Pick'} {selected} · {'선두' if locale == 'ko' else 'Lead'} {leader} · T{tick}"
        rounded(draw, (668, y, 1210, y + 54), 13, fill=(34, 32, 41), outline=(93, 83, 52), width=1)
        draw.text((682, y + 15), truncate(draw, row, font(16, True), 510), font=font(16, True), fill=TEXT)
        y += 64
    if not live_races:
        draw.text((676, 214), "현재 진행 중인 경마가 없습니다." if locale == "ko" else "No live horse race.", font=font(18), fill=MUTED)

    recent = list(recent_races)[:2]
    if recent:
        y = 515
        draw.text((670, y), "최근 결승" if locale == "ko" else "Recent Finishes", font=font(17, True), fill=MUTED)
        for record in recent:
            y += 30
            text = f"{record.get('winner', '-')} · {int(record.get('net', 0) or 0):+,}"
            draw.text((680, y), truncate(draw, text, font(15, True), 500), font=font(15, True), fill=GREEN)

    draw.text((52, 678), time.strftime("%Y-%m-%d %H:%M:%S"), font=font(14), fill=MUTED)
    draw.text((1230, 678), f"ABADDON v{VERSION}", font=font(14, True), fill=PURPLE, anchor="ra")
    return png(image)
