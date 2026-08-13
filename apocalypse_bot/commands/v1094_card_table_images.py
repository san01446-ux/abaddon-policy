from __future__ import annotations

"""Dynamic card-table PNG renderers for all v10.9 card sessions."""

from io import BytesIO
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw

from apocalypse_bot.commands.v1094_visual_core import (
    VERSION, card_label, clean_text, draw_hwatu_card, draw_playing_card,
    draw_wrapped, fit_font, font, png, rounded, truncate,
)

BG=(16,15,20); TABLE=(33,31,38); PANEL=(47,44,53); TEXT=(245,242,235); MUTED=(188,181,194)
GOLD=(235,190,77); GREEN=(80,221,151); BLUE=(87,163,244); RED=(235,79,98); PURPLE=(178,105,245)


def _locale(session: Any) -> str:
    return str(getattr(session, "locale", getattr(session, "public_locale", "ko")))


def _kind(session: Any) -> str:
    return str(getattr(session, "variant", getattr(session, "mode", getattr(session, "kind", session.__class__.__name__))))


def _title(kind: str, locale: str) -> str:
    if locale == "ko": return kind
    try:
        from apocalypse_bot.commands.v1060_authentic_card_games import GAME_EN
        return GAME_EN.get(kind, kind)
    except Exception:
        return kind


def _names(session: Any) -> Mapping[int, str]:
    value=getattr(session,"names",{})
    return value if isinstance(value, Mapping) else {}


def _player_ids(session: Any) -> list[int]:
    return [int(v) for v in getattr(session,"player_ids",list(_names(session).keys()))]


def _current(session: Any) -> int | None:
    for attr in ("current_uid",):
        try:
            value=getattr(session,attr)
            if value is not None:return int(value)
        except Exception: pass
    engine=getattr(session,"engine",None)
    if engine is not None:
        try:return int(engine.current_uid)
        except Exception:pass
    return None


def _header(draw: ImageDraw.ImageDraw, session: Any, subtitle: str) -> tuple[str,str]:
    locale=_locale(session); kind=_kind(session)
    draw.text((52,34), f"ABADDON · {_title(kind,locale)}", font=font(38,True), fill=TEXT)
    draw.text((54,84), subtitle, font=font(20,True), fill=GOLD)
    pot=int(getattr(session,"pot",0) or 0)
    draw.text((1190,47), (f"팟 {pot:,}" if locale=="ko" else f"Pot {pot:,}"), font=font(24,True), fill=GREEN, anchor="ra")
    return locale,kind


def _footer(draw: ImageDraw.ImageDraw, session: Any, note: str="") -> None:
    locale=_locale(session)
    current=_current(session); names=_names(session)
    turn=(names.get(current,"ABADDON") if current is not None else ("종료" if locale=="ko" else "Finished"))
    text=(f"현재 차례: {turn} · 음수 잔액 허용 · 자유 레이즈(안전 한도)" if locale=="ko" else f"Turn: {turn} · negative balance · free raise with safety limit")
    if note:text += f" · {clean_text(note)}"
    draw.text((52,676), truncate(draw,text,font(17),1170), font=font(17), fill=MUTED)
    draw.text((1228,676), f"v{VERSION}", font=font(16,True), fill=PURPLE, anchor="ra")


def _base() -> tuple[Image.Image,ImageDraw.ImageDraw]:
    image=Image.new("RGB",(1280,720),BG); draw=ImageDraw.Draw(image)
    rounded(draw,(18,18,1262,702),30,fill=TABLE,outline=(122,112,139),width=4)
    return image,draw


def _players_panel(draw: ImageDraw.ImageDraw, session: Any, y: int=510, height: int=145) -> None:
    ids=_player_ids(session); names=_names(session); current=_current(session)
    n=max(1,len(ids)); gap=12; width=(1176-gap*(n-1))//n
    betting=getattr(session,"betting",None)
    folded=set(getattr(betting,"folded",set()) if betting else set()) | set(getattr(session,"permanent_folded",set()))
    hands=getattr(session,"hands",{})
    for index,uid in enumerate(ids):
        x=52+index*(width+gap); outline=BLUE if uid==current else (RED if uid in folded else (91,86,101))
        rounded(draw,(x,y,x+width,y+height),18,fill=PANEL,outline=outline,width=3 if uid==current else 2)
        name=names.get(uid,"ABADDON")
        draw.text((x+14,y+12),truncate(draw,name,font(18,True),width-28),font=font(18,True),fill=TEXT)
        count=len(hands.get(uid,[])) if isinstance(hands,Mapping) else 0
        status=("폴드" if _locale(session)=="ko" else "Folded") if uid in folded else (f"{count}장" if _locale(session)=="ko" else f"{count} cards")
        if betting is not None:
            status+=f" · {int(getattr(betting,'round_bets',{}).get(uid,0)):,}"
        draw.text((x+14,y+43),truncate(draw,status,font(15),width-28),font=font(15),fill=RED if uid in folded else MUTED)
        # Show public upcards only.
        up=getattr(session,"upcards",{}).get(uid,[]) if isinstance(getattr(session,"upcards",{}),Mapping) else []
        cx=x+14
        for card in list(up)[:4]:
            draw_playing_card(draw,(cx,y+70,cx+44,y+130),card);cx+=49


def _poker(session: Any, embed: Any|None) -> BytesIO:
    image,draw=_base(); locale,kind=_header(draw,session,clean_text(getattr(session,"stage_label",getattr(session,"stage","Table"))))
    board=list(getattr(session,"board",[]) or [])
    draw.text((52,128),"커뮤니티 보드" if locale=="ko" else "Community board",font=font(18,True),fill=MUTED)
    x=52
    for i in range(5):
        draw_playing_card(draw,(x,160,x+112,318),board[i] if i<len(board) else None,hidden=i>=len(board));x+=126
    rounded(draw,(710,126,1228,470),22,fill=PANEL,outline=(91,86,101),width=2)
    draw.text((738,150),"진행 상황" if locale=="ko" else "Action",font=font(22,True),fill=GOLD)
    last=clean_text(getattr(session,"last_action",""))
    draw_wrapped(draw,(738,190),last,font(19),455,fill=TEXT,max_lines=4,spacing=8)
    betting=getattr(session,"betting",None)
    if betting is not None:
        draw.text((738,330),(f"현재 콜 {int(getattr(betting,'current_bet',0)):,}" if locale=="ko" else f"Current bet {int(getattr(betting,'current_bet',0)):,}"),font=font(20,True),fill=BLUE)
    if getattr(session,"exchange_pending",None):
        draw.text((738,376),"교환 선택 대기" if locale=="ko" else "Waiting for draw",font=font(18,True),fill=RED)
    if embed is not None and getattr(session,"done",False):
        draw_wrapped(draw,(738,410),getattr(embed,"description","") or "",font(15),455,fill=MUTED,max_lines=2)
    _players_panel(draw,session);_footer(draw,session)
    return png(image)


def _hwatu(session: Any, embed: Any|None) -> BytesIO:
    image,draw=_base(); locale,kind=_header(draw,session,"실전 화투 테이블" if locale_safe(session)=="ko" else "Live hwatu table")
    engine=getattr(session,"engine",session); floor=list(getattr(engine,"floor",[]) or [])
    draw.text((52,126),"바닥패" if locale=="ko" else "Floor",font=font(19,True),fill=MUTED)
    for i,card in enumerate(floor[:12]):
        row=i//6;col=i%6;x=52+col*91;y=158+row*132
        draw_hwatu_card(draw,(x,y,x+78,y+116),card)
    rounded(draw,(630,126,1228,455),22,fill=PANEL,outline=(91,86,101),width=2)
    draw.text((656,148),"획득·점수" if locale=="ko" else "Captured · score",font=font(21,True),fill=GOLD)
    names=_names(session);ids=_player_ids(session);captured=getattr(engine,"captured",{})
    y=190
    for uid in ids:
        cards=captured.get(uid,[]) if isinstance(captured,Mapping) else []
        score=0;junk=0
        try:
            summary=session.score(uid);score=int(summary.score);junk=int(summary.junk_points)
        except Exception:
            score=int(getattr(session,"scores",{}).get(uid,0) if isinstance(getattr(session,"scores",{}),Mapping) else 0)
        go=int(getattr(session,"go_counts",{}).get(uid,0) if isinstance(getattr(session,"go_counts",{}),Mapping) else 0)
        line=f"{names.get(uid,'ABADDON')} · {score}{'점' if locale=='ko' else ' pts'} · {'피' if locale=='ko' else 'junk'} {junk} · {'고' if locale=='ko' else 'Go'} {go} · {len(cards)}"
        draw.text((656,y),truncate(draw,line,font(18,True),540),font=font(18,True),fill=BLUE if uid==_current(session) else TEXT);y+=42
    stock=len(getattr(engine,"stock",[]) or [])
    draw.text((656,398),(f"남은 더미 {stock}장" if locale=="ko" else f"Stock {stock}"),font=font(18,True),fill=GREEN)
    _players_panel(draw,session,y=490,height=165);_footer(draw,session,clean_text(getattr(session,"last_action","")))
    return png(image)


def locale_safe(session:Any)->str:return _locale(session)


def _blackjack(session: Any, embed: Any|None) -> BytesIO:
    image,draw=_base();locale,kind=_header(draw,session,"딜러와 21 승부" if locale_safe(session)=="ko" else "Beat the dealer to 21")
    dealer=list(getattr(session,"dealer",[]) or [])
    draw.text((52,126),"딜러" if locale=="ko" else "Dealer",font=font(20,True),fill=MUTED)
    x=52
    for i in range(max(2,len(dealer))):
        hidden=not getattr(session,"done",False) and i>0
        draw_playing_card(draw,(x,158,x+112,318),dealer[i] if i<len(dealer) else None,hidden=hidden);x+=126
    hands=getattr(session,"hands",{});names=_names(session);ids=_player_ids(session)
    y=350
    for uid in ids:
        rounded(draw,(52,y,1228,y+78),16,fill=PANEL,outline=BLUE if uid==_current(session) else (91,86,101),width=2)
        draw.text((68,y+12),truncate(draw,names.get(uid,"ABADDON"),font(18,True),210),font=font(18,True),fill=TEXT)
        cards=list(hands.get(uid,[]) if isinstance(hands,Mapping) else [])
        cx=290
        for card in cards[:8]:
            draw_playing_card(draw,(cx,y+8,cx+45,y+68),card);cx+=50
        try:total=session.value(cards)
        except Exception:total="-"
        draw.text((1160,y+24),str(total),font=font(24,True),fill=GOLD,anchor="ra");y+=88
        if y>620:break
    _footer(draw,session);return png(image)


def _baccarat(session: Any, embed: Any|None) -> BytesIO:
    image,draw=_base();locale,kind=_header(draw,session,"플레이어 · 뱅커 · 타이" if locale_safe(session)=="ko" else "Player · Banker · Tie")
    result=getattr(session,"result",None)
    player=[];banker=[];outcome=""
    if result:
        try:player,banker,outcome=result
        except Exception:pass
    for title,cards,y,color in (("플레이어" if locale=="ko" else "Player",player,150,BLUE),("뱅커" if locale=="ko" else "Banker",banker,350,RED)):
        draw.text((52,y-30),title,font=font(22,True),fill=color);x=52
        for i in range(3):draw_playing_card(draw,(x,y,x+112,y+158),cards[i] if i<len(cards) else None,hidden=i>=len(cards));x+=126
    rounded(draw,(520,130,1228,580),24,fill=PANEL,outline=(91,86,101),width=2)
    draw.text((548,154),"선택 현황" if locale=="ko" else "Selections",font=font(22,True),fill=GOLD)
    choices=getattr(session,"choices",{});names=_names(session);y=205
    for uid in _player_ids(session):
        value=choices.get(uid,"대기" if locale=="ko" else "Waiting") if isinstance(choices,Mapping) else "-"
        draw.text((548,y),truncate(draw,f"{names.get(uid,'ABADDON')} · {value}",font(18,True),630),font=font(18,True),fill=TEXT);y+=42
    if outcome:draw.text((548,500),f"결과: {outcome}" if locale=="ko" else f"Result: {outcome}",font=font(26,True),fill=GREEN)
    _footer(draw,session);return png(image)


def _seotda(session: Any, embed: Any|None) -> BytesIO:
    image,draw=_base();locale,kind=_header(draw,session,f"{getattr(session,'street',1)}차 베팅" if locale_safe(session)=="ko" else f"Betting round {getattr(session,'street',1)}")
    hands=getattr(session,"hands",{});names=_names(session);ids=_player_ids(session);current=_current(session);y=150
    for uid in ids:
        rounded(draw,(52,y,1228,y+104),18,fill=PANEL,outline=BLUE if uid==current else (91,86,101),width=3 if uid==current else 2)
        draw.text((70,y+16),truncate(draw,names.get(uid,"ABADDON"),font(20,True),250),font=font(20,True),fill=TEXT)
        cards=list(hands.get(uid,[]) if isinstance(hands,Mapping) else [])
        # Public table keeps hands hidden until final.
        for i in range(2):draw_hwatu_card(draw,(330+i*92,y+8,408+i*92,y+96),cards[i] if i<len(cards) else object(),hidden=not getattr(session,"done",False))
        betting=getattr(session,"betting",None);amount=int(getattr(betting,"round_bets",{}).get(uid,0) if betting else 0)
        draw.text((1160,y+36),f"{amount:,}",font=font(23,True),fill=GOLD,anchor="ra");y+=116
        if y>610:break
    _footer(draw,session);return png(image)


def _onecard(session: Any, embed: Any|None) -> BytesIO:
    image,draw=_base();locale,kind=_header(draw,session,"같은 숫자·무늬를 내세요" if locale_safe(session)=="ko" else "Match rank or suit")
    discard=list(getattr(session,"discard",[]) or []);top=discard[-1] if discard else None
    draw.text((80,150),"바닥 카드" if locale=="ko" else "Top card",font=font(22,True),fill=MUTED)
    draw_playing_card(draw,(86,195,250,425),top)
    penalty=int(getattr(session,"penalty",0) or 0)
    draw.text((82,460),f"{'누적 벌칙' if locale=='ko' else 'Penalty'} {penalty}",font=font(22,True),fill=RED if penalty else GREEN)

    # Keep the player list on the right so it never overlaps the top card.
    rounded(draw,(330,132,1228,620),22,fill=PANEL,outline=(91,86,101),width=2)
    draw.text((356,156),"참가자" if locale=="ko" else "Players",font=font(22,True),fill=GOLD)
    ids=_player_ids(session);names=_names(session);hands=getattr(session,"hands",{});current=_current(session)
    y=205
    for uid in ids:
        count=len(hands.get(uid,[]) if isinstance(hands,Mapping) else [])
        outline=BLUE if uid==current else (91,86,101)
        rounded(draw,(356,y,1200,y+74),15,fill=TABLE,outline=outline,width=3 if uid==current else 2)
        draw.text((374,y+12),truncate(draw,names.get(uid,"ABADDON"),font(18,True),440),font=font(18,True),fill=TEXT)
        draw.text((1168,y+16),f"{count}{'장' if locale=='ko' else ' cards'}",font=font(19,True),fill=GOLD,anchor="ra")
        y+=86
        if y>560:break
    _footer(draw,session,clean_text(getattr(session,"last_action","")));return png(image)


def _joker(session: Any, embed: Any|None) -> BytesIO:
    image,draw=_base();locale,kind=_header(draw,session,"마지막 조커를 피하세요" if locale_safe(session)=="ko" else "Avoid the final Joker")
    ids=_player_ids(session);names=_names(session);hands=getattr(session,"hands",{});current=_current(session);y=145
    for uid in ids:
        count=len(hands.get(uid,[]) if isinstance(hands,Mapping) else [])
        rounded(draw,(52,y,1228,y+82),18,fill=PANEL,outline=BLUE if uid==current else (91,86,101),width=2)
        draw.text((72,y+18),truncate(draw,names.get(uid,"ABADDON"),font(20,True),350),font=font(20,True),fill=TEXT)
        x=480
        for _ in range(min(count,12)):
            draw_playing_card(draw,(x,y+10,x+38,y+70),None,hidden=True);x+=42
        draw.text((1160,y+25),f"{count}",font=font(22,True),fill=GOLD,anchor="ra");y+=92
        if y>620:break
    _footer(draw,session);return png(image)


def _generic(session: Any, embed: Any|None) -> BytesIO:
    image,draw=_base();locale,kind=_header(draw,session,"이미지 테이블" if locale_safe(session)=="ko" else "Image table")
    last=clean_text(getattr(session,"last_action",getattr(embed,"description","") if embed else ""))
    rounded(draw,(52,130,1228,450),22,fill=PANEL,outline=(91,86,101),width=2)
    draw.text((78,154),"현재 진행" if locale=="ko" else "Current action",font=font(23,True),fill=GOLD)
    draw_wrapped(draw,(78,202),last,font(22),1100,fill=TEXT,max_lines=6,spacing=10)
    _players_panel(draw,session,y=485,height=170);_footer(draw,session);return png(image)




def _final_overlay(buffer: BytesIO, session: Any, embed: Any|None) -> BytesIO:
    if not getattr(session, "done", False) or embed is None:
        return buffer
    try:
        buffer.seek(0)
        image=Image.open(buffer).convert("RGB")
        draw=ImageDraw.Draw(image)
        locale=_locale(session)
        lines=[]
        description=clean_text(getattr(embed,"description","") or "")
        if description:
            lines.append(description)
        for field in list(getattr(embed,"fields",[]) or []):
            name=clean_text(getattr(field,"name","") or "")
            value=clean_text(getattr(field,"value","") or "")
            if name or value:
                lines.append(f"{name}: {value}" if name else value)
        summary=" · ".join(lines)
        # The final result must always be readable even when the game-specific
        # table used this area for action information.
        rounded(draw,(682,112,1236,482),22,fill=(25,23,31),outline=GREEN,width=4)
        draw.text((710,136),"🏆 최종 승부 결과" if locale=="ko" else "🏆 Final Result",font=font(25,True),fill=GOLD)
        draw_wrapped(draw,(710,184),summary,font(17),490,fill=TEXT,max_lines=11,spacing=7)
        return png(image)
    except Exception:
        try: buffer.seek(0)
        except Exception: pass
        return buffer

def render_session_table(session: Any, embed: Any|None=None) -> BytesIO | None:
    if session is None or not hasattr(session,"player_ids"):
        return None
    name=session.__class__.__name__
    try:
        if hasattr(session,"engine") and hasattr(getattr(session,"engine"),"floor"):
            result=_hwatu(session,embed)
        elif name in {"CaptureHwatuSession"}:
            result=_hwatu(session,embed)
        elif "Poker" in name or (hasattr(session,"betting") and hasattr(session,"hands") and hasattr(session,"board")):
            result=_poker(session,embed)
        elif "Blackjack" in name:
            result=_blackjack(session,embed)
        elif "Baccarat" in name:
            result=_baccarat(session,embed)
        elif "Seotda" in name or "KoreanShowdown" in name:
            result=_seotda(session,embed)
        elif "OneCard" in name:
            result=_onecard(session,embed)
        elif "Joker" in name or "OldMaid" in name:
            result=_joker(session,embed)
        else:
            result=_generic(session,embed)
        return _final_overlay(result,session,embed)
    except Exception:
        return None


def render_private_hand(*, locale: str, title: str, cards: Sequence[Any], note: str="", hwatu: bool=False, hidden_indices: set[int]|None=None) -> BytesIO:
    image,draw=_base();draw.text((52,38),title,font=fit_font(draw,title,1140,36,22,bold=True),fill=TEXT)
    draw.text((54,88),"본인에게만 보이는 비공개 패" if locale=="ko" else "Private hand · visible only to you",font=font(18,True),fill=GREEN)
    hidden_indices=hidden_indices or set()
    all_cards=list(cards)
    shown=all_cards[:30]
    count=max(1,len(shown));cols=min(10,count);rows=(count+cols-1)//cols
    usable_h=430
    width_based=max(52,(1160-(cols-1)*10)//cols)
    height_based=max(52,int((usable_h-(rows-1)*12)/max(1,rows)/1.42))
    card_w=min(104,width_based,height_based);card_h=int(card_w*1.42)
    start_y=145;row_gap=12
    for i,card in enumerate(shown):
        row=i//cols;col=i%cols;x=52+col*(card_w+10);y=start_y+row*(card_h+row_gap)
        if hwatu:draw_hwatu_card(draw,(x,y,x+card_w,y+card_h),card,hidden=i in hidden_indices)
        else:draw_playing_card(draw,(x,y,x+card_w,y+card_h),card,hidden=i in hidden_indices)
    extra=max(0,len(all_cards)-len(shown))
    notes=[]
    if extra:notes.append((f"외 {extra}장" if locale=="ko" else f"+{extra} more cards"))
    if note:notes.append(note)
    if notes:
        draw_wrapped(draw,(52,602)," · ".join(notes),font(18),1160,fill=GOLD,max_lines=2)
    draw.text((52,676),"이 이미지는 메모리에서 생성되며 공개 테이블에는 노출되지 않습니다." if locale=="ko" else "Generated in memory and never shown on the public table.",font=font(16),fill=MUTED)
    return png(image)
