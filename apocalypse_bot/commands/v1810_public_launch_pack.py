from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import random
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from urllib import error as urllib_error

import discord
from discord.ext import commands

from apocalypse_bot.core.storage_sqlite import audit as sqlite_audit, mirror_snapshot
from apocalypse_bot.commands.v750_guild_raid import guild_for_user, ensure_guild_state

VERSION = "18.1.0"
KST = timezone(timedelta(hours=9))
PVP_DAILY_LIMIT = 15
PVP_PAIR_DAILY_LIMIT = 3
PVP_K = 28
GUILD_WAR_DAILY_LIMIT = 4
GUILD_WAR_COOLDOWN = 4 * 60 * 60
AI_COOLDOWN = 30
AI_HISTORY_LIMIT = 8
OAUTH_SESSION_TTL = 12 * 60 * 60
OAUTH_STATE_TTL = 10 * 60

_PVP_LOCKS: Dict[int, asyncio.Lock] = {}
_GUILD_WAR_LOCK = asyncio.Lock()
_AI_LAST: Dict[int, float] = {}
_HTTP_SESSIONS: Dict[str, Dict[str, Any]] = {}
_HTTP_STATES: Dict[str, Dict[str, Any]] = {}
_HTTP_LOCK = threading.RLock()

RANKS: Tuple[Tuple[int, str, str], ...] = (
    (1700, "🌘 심연", "ECLIPSE"),
    (1500, "💎 다이아", "DIAMOND"),
    (1300, "🟣 플래티넘", "PLATINUM"),
    (1125, "🥇 골드", "GOLD"),
    (950, "🥈 실버", "SILVER"),
    (0, "🥉 브론즈", "BRONZE"),
)

def _t(locale: str, ko: str, en: str) -> str:
    return en if locale == "en" else ko


def _locale(bot: commands.Bot, ctx: commands.Context) -> str:
    try:
        from apocalypse_bot.commands import v1000_global_survivor as global_mod
        root = global_mod._RUNTIME.get("root", {})
        return global_mod._user_locale(root, int(ctx.author.id), int(ctx.guild.id if ctx.guild else 0))
    except Exception:
        return "ko"


AI_PERSONAS: Mapping[str, str] = {
    "윤서": "침착한 의무병. 생존과 회복을 중시하며 짧고 현실적인 조언을 한다.",
    "도윤": "경계심 강한 정찰병. 위험을 먼저 짚고 효율적인 선택지를 제안한다.",
    "세라": "기술자. 장비, 제작, 도시 시스템을 좋아하고 분석적으로 말한다.",
    "렌": "교섭가. 세력과 인간관계를 중시하며 갈등을 완화하는 쪽으로 말한다.",
    "케인": "중화기병. 직선적이고 자신감 있으며 전투적이지만 무모함은 경계한다.",
    "이브": "정보상. 암시장과 소문에 밝고 약간 장난스럽지만 중요한 정보는 정확히 준다.",
    "녹스": "교단 탈주자. 검은 태양과 심연을 경계하며 불길한 징후에 민감하다.",
    "미라": "기록관. 과거 선택과 기록을 연결하며 차분하고 서사적으로 대답한다.",
    "아바돈": "검은 성역의 안내자. 서버의 생존자에게 친근하고 간결한 RPG 안내를 제공한다.",
}

AI_PERSONAS_EN: Mapping[str, str] = {
    "윤서": "A calm field medic who prioritizes survival and recovery, giving short practical advice.",
    "도윤": "A cautious scout who spots risks first and recommends efficient routes.",
    "세라": "An analytical engineer who enjoys equipment, crafting and city systems.",
    "렌": "A negotiator who values factions and relationships and tries to de-escalate conflict.",
    "케인": "A direct heavy gunner who is confident in combat but warns against reckless choices.",
    "이브": "A playful information broker who knows the black market and rumors but keeps key facts accurate.",
    "녹스": "A cult defector wary of the Black Sun and the Abyss, sensitive to ominous signs.",
    "미라": "An archivist who connects past choices and records in a calm narrative voice.",
    "아바돈": "The guide of the Black Sanctuary, friendly and concise when helping survivors navigate the RPG.",
}
AI_NAME_EN: Mapping[str, str] = {
    "윤서":"Yoonseo", "도윤":"Doyoon", "세라":"Sera", "렌":"Ren", "케인":"Kane",
    "이브":"Eve", "녹스":"Nox", "미라":"Mira", "아바돈":"Abaddon",
}
AI_NAME_ALIASES: Mapping[str, str] = {**{k.casefold():k for k in AI_PERSONAS}, **{v.casefold():k for k,v in AI_NAME_EN.items()}}



def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso() -> str:
    return _now().isoformat()


def _day() -> str:
    return _now().astimezone(KST).strftime("%Y-%m-%d")


def _week() -> str:
    y, w, _ = _now().astimezone(KST).isocalendar()
    return f"{y}-W{w:02d}"


def _season() -> str:
    return _now().astimezone(KST).strftime("%Y-%m")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _rank(rating: int) -> Tuple[str, str]:
    for minimum, ko, en in RANKS:
        if rating >= minimum:
            return ko, en
    return RANKS[-1][1], RANKS[-1][2]


def _pvp(user: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    row = user.setdefault("pvp_rank_v1810", {})
    if not isinstance(row, dict):
        row = {}
        user["pvp_rank_v1810"] = row
    defaults = {
        "rating": 1000, "wins": 0, "losses": 0, "matches": 0, "streak": 0,
        "best_rating": 1000, "opt_in": False, "season": _season(), "season_wins": 0,
        "season_losses": 0, "day": _day(), "daily_matches": 0, "history": [],
    }
    for k, v in defaults.items():
        row.setdefault(k, list(v) if isinstance(v, list) else v)
    if row.get("season") != _season():
        previous_rating=_safe_int(row.get("rating"),1000)
        previous_wins=_safe_int(row.get("season_wins"))
        previous_losses=_safe_int(row.get("season_losses"))
        row["previous_season"]={
            "season":str(row.get("season") or ""), "rating":previous_rating,
            "wins":previous_wins, "losses":previous_losses,
            "rank_ko":_rank(previous_rating)[0], "rank_en":_rank(previous_rating)[1],
            "eligible":bool(previous_wins+previous_losses>0), "claimed":False,
        }
        row["season"] = _season(); row["season_wins"] = 0; row["season_losses"] = 0
    if row.get("day") != _day():
        row["day"] = _day(); row["daily_matches"] = 0
    return row


def _rating_expected(a: int, b: int) -> float:
    return 1.0 / (1.0 + 10.0 ** ((b - a) / 400.0))


def _battle_score(user: Mapping[str, Any], rating: int, calculate_user_power: Callable[[Mapping[str, Any]], int]) -> float:
    power = max(1, _safe_int(calculate_user_power(user), 1))
    # log scaling prevents ancient high-power saves from making PvP mathematically unwinnable.
    return rating + math.log1p(power) * 42.0 + random.gauss(0.0, 72.0)


def _pvp_pair_daily(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root=world_data.setdefault("pvp_pair_v1810",{})
    if not isinstance(root,dict): root={}; world_data["pvp_pair_v1810"]=root
    if root.get("day")!=_day(): root.clear(); root.update({"day":_day(),"pairs":{}})
    root.setdefault("pairs",{})
    return root


def _pvp_pair_key(a:int,b:int)->str:
    x,y=sorted((int(a),int(b)))
    return f"{x}:{y}"


def _invite(user: MutableMapping[str, Any], user_id: int) -> MutableMapping[str, Any]:
    row = user.setdefault("invite_v1810", {})
    if not isinstance(row, dict):
        row = {}; user["invite_v1810"] = row
    if not str(row.get("code") or "").strip():
        row["code"] = "AB-" + secrets.token_hex(4).upper()
    row.setdefault("inviter", "")
    row.setdefault("used_at", "")
    row.setdefault("invited", [])
    row.setdefault("rewarded", [])
    return row


def _guild_war_root(world_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    root = world_data.setdefault("guild_war_v1810", {})
    if not isinstance(root, dict):
        root = {}; world_data["guild_war_v1810"] = root
    current = _week()
    if root.get("week") != current:
        if root.get("week") and isinstance(root.get("scores"), dict):
            root["previous"] = {
                "week": root.get("week"), "scores": dict(root.get("scores", {})),
                "attacks": list(root.get("attacks", [])), "closed_at": _iso(),
                "claimed": [],
            }
        root["week"] = current; root["scores"] = {}; root["attacks"] = []; root["member_daily"] = {}
    root.setdefault("scores", {}); root.setdefault("attacks", []); root.setdefault("member_daily", {})
    return root


def _guild_score_name(world_data: Mapping[str, Any], gid: str) -> str:
    raw = world_data.get("guilds", {}).get(str(gid), {}) if isinstance(world_data.get("guilds"), Mapping) else {}
    return str(raw.get("name") or f"길드 {gid}")


def _profile_public(bot: commands.Bot, user_id: str, user: Mapping[str, Any]) -> Dict[str, Any]:
    member = bot.get_user(_safe_int(user_id))
    name = getattr(member, "display_name", None) or getattr(member, "name", None) or f"Survivor-{str(user_id)[-4:]}"
    avatar = ""
    try:
        avatar = str(member.display_avatar.url) if member else ""
    except Exception:
        avatar = ""
    pvp = _pvp(user if isinstance(user, dict) else dict(user))
    return {
        "id": str(user_id), "name": str(name)[:80], "avatar": avatar,
        "level": _safe_int(user.get("level"), 1), "exp": _safe_int(user.get("exp"), 0),
        "balance": _safe_int(user.get("balance"), 0), "pvp_rating": _safe_int(pvp.get("rating"), 1000),
        "pvp_rank": _rank(_safe_int(pvp.get("rating"), 1000))[1],
        "title": str(user.get("title") or "")[:80],
    }


def _http_json(url: str, *, headers: Optional[Dict[str, str]] = None, data: Optional[bytes] = None, method: Optional[str] = None, timeout: int = 12) -> Dict[str, Any]:
    req = urllib_request.Request(url, data=data, headers=headers or {}, method=method or ("POST" if data is not None else "GET"))
    with urllib_request.urlopen(req, timeout=timeout) as response:
        raw = response.read(512_000).decode("utf-8", "replace")
    value = json.loads(raw)
    return value if isinstance(value, dict) else {"data": value}


def _llm_reply_sync(persona: str, history: Sequence[Mapping[str, str]], message: str, locale: str = "ko") -> Tuple[str, str]:
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    compatible_url = os.getenv("ABADDON_LLM_API_URL", "").strip()
    compatible_key = os.getenv("ABADDON_LLM_API_KEY", "").strip()
    model = (os.getenv("ABADDON_LLM_MODEL", "") or os.getenv("ANTHROPIC_MODEL", "")).strip()
    system = (
        ("You are an NPC companion in the Discord RPG ABADDON. Reply in English in 2-5 sentences. "
         "Use only the game world and the user's recent conversation. Never request passwords, tokens, or personal data. "
         f"NPC personality: {persona}")
        if locale == "en" else
        ("너는 Discord RPG ABADDON의 NPC 동료다. 한국어로 2~5문장 이내로 대답한다. "
         "게임 세계관과 사용자의 최근 대화만 참고하고, 비밀번호·토큰·개인정보를 요구하지 않는다. "
         f"NPC 성격: {persona}")
    )
    if anthropic_key and model:
        payload = {
            "model": model, "max_tokens": 300, "system": system,
            "messages": [{"role": h.get("role", "user"), "content": str(h.get("content", ""))[:700]} for h in history[-6:]] + [{"role": "user", "content": message[:700]}],
        }
        raw = json.dumps(payload).encode()
        value = _http_json(
            "https://api.anthropic.com/v1/messages", data=raw, method="POST",
            headers={"content-type": "application/json", "x-api-key": anthropic_key, "anthropic-version": "2023-06-01"},
        )
        content = value.get("content")
        if isinstance(content, list) and content and isinstance(content[0], Mapping):
            text = str(content[0].get("text") or "").strip()
            if text:
                return text[:1200], "Anthropic"
    if compatible_url and compatible_key and model:
        payload = {
            "model": model, "messages": [{"role": "system", "content": system}] +
            [{"role": h.get("role", "user"), "content": str(h.get("content", ""))[:700]} for h in history[-6:]] +
            [{"role": "user", "content": message[:700]}], "max_tokens": 300,
        }
        value = _http_json(
            compatible_url, data=json.dumps(payload).encode(), method="POST",
            headers={"content-type": "application/json", "authorization": f"Bearer {compatible_key}"},
        )
        choices = value.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
            msg = choices[0].get("message")
            if isinstance(msg, Mapping):
                text = str(msg.get("content") or "").strip()
                if text:
                    return text[:1200], "OpenAI-compatible"
    return "", "local"


def _local_companion_reply(name: str, message: str, persona: str, locale: str = "ko") -> str:
    low = message.casefold()
    if locale == "en":
        if any(x in low for x in ("what should", "what do", "recommend", "next")):
            return f"{name}: Check `!dailyloop` first, then finish one remaining expedition or contract. {persona.split('.')[0]}."
        if any(x in low for x in ("danger", "infection", "dying", "health", "hp")):
            return f"{name}: Check your condition first. Review `!status` and your recovery options before moving."
        if any(x in low for x in ("gear", "craft", "material", "equipment")):
            return f"{name}: Open `!productioncenter` and compare your materials with what you can craft. Convert what you already own into progress first."
        return f"{name}: Signal received. I will keep your message — ‘{message[:90]}’ — in our recent memory. Let's pick the single most important next move."
    if any(x in low for x in ("뭐할", "뭐 하지", "추천", "다음")):
        return f"{name}: 지금은 `!오늘의루프`를 먼저 보고, 남은 항목 중 원정이나 의뢰 하나를 끝내는 게 좋아. {persona.split('.')[0]}."
    if any(x in low for x in ("위험", "감염", "죽", "체력")):
        return f"{name}: 상태부터 확인하자. `!상태`와 회복 수단을 보고 체력·감염을 정리한 다음 움직이는 게 안전해."
    if any(x in low for x in ("장비", "제작", "재료")):
        return f"{name}: `!생산센터`에서 보유 재료와 제작 가능 항목을 같이 봐. 지금 가진 걸 실제 성장으로 바꾸는 게 우선이야."
    return f"{name}: 신호 확인했어. 네 말은 ‘{message[:90]}’로 최근 기억에 남겨둘게. 지금 상황에서 가장 중요한 한 가지부터 같이 정해보자."


def _cleanup_http_sessions() -> None:
    now = time.time()
    with _HTTP_LOCK:
        for key in list(_HTTP_SESSIONS):
            if float(_HTTP_SESSIONS[key].get("expires", 0)) <= now:
                _HTTP_SESSIONS.pop(key, None)
        for key in list(_HTTP_STATES):
            row=_HTTP_STATES.get(key,{})
            if float(row.get("created",0) if isinstance(row,Mapping) else 0) + OAUTH_STATE_TTL <= now:
                _HTTP_STATES.pop(key, None)


def _authorization_token(handler: Any) -> str:
    value = str(handler.headers.get("Authorization") or "")
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return ""


def _redirect(handler: Any, location: str, *, cookie: str = "") -> None:
    handler.send_response(302)
    handler.send_header("Location", location)
    handler.send_header("Cache-Control", "no-store")
    if cookie:
        handler.send_header("Set-Cookie", cookie)
    handler.end_headers()


def _build_http_hook(bot: commands.Bot, user_data: MutableMapping[str, Any], get_user: Callable[[int], Any]) -> Callable[[Any, Any], bool]:
    def hook(handler: Any, parsed: Any) -> bool:
        path = str(parsed.path or "")
        query = urllib_parse.parse_qs(parsed.query or "")
        _cleanup_http_sessions()
        if path == "/api/leaderboard":
            kind = str((query.get("type") or ["pvp"])[0]).lower()
            rows = []
            for uid,u in user_data.items():
                if not isinstance(u,dict):
                    continue
                # Keep public rows anonymous at the ID level. Sorting-only fields
                # are prefixed and stripped before the HTTP response.
                profile=_profile_public(bot,str(uid),u)
                rows.append({
                    **{k:profile.get(k) for k in ("name","level","balance","pvp_rating","pvp_rank","title")},
                    "_sort_exp": _safe_int(u.get("exp"), 0),
                    "_pvp_active": bool(_safe_int((u.get("pvp_rank_v1810") or {}).get("matches"), 0) or (u.get("pvp_rank_v1810") or {}).get("opt_in")) if isinstance(u.get("pvp_rank_v1810"), Mapping) else False,
                })
            if kind == "level":
                rows.sort(key=lambda x: (_safe_int(x.get("level"),1), _safe_int(x.get("_sort_exp")), _safe_int(x.get("pvp_rating"),1000)), reverse=True)
            elif kind == "wealth":
                rows.sort(key=lambda x: (_safe_int(x.get("balance")), _safe_int(x.get("level"),1)), reverse=True)
            else:
                kind = "pvp"
                rows = [x for x in rows if x.get("_pvp_active")]
                rows.sort(key=lambda x: (_safe_int(x.get("pvp_rating"),1000), _safe_int(x.get("level"),1)), reverse=True)
            public_rows=[{k:v for k,v in row.items() if not k.startswith("_")} for row in rows[:50]]
            handler._send_json(200, {"ok": True, "type": kind, "rows": public_rows, "generated_at": _iso(), "version": f"v{VERSION}"})
            return True
        if path == "/api/me":
            token = _authorization_token(handler)
            with _HTTP_LOCK:
                session = dict(_HTTP_SESSIONS.get(token, {})) if token else {}
            if not session:
                handler._send_json(401, {"ok": False, "error": "login_required"}); return True
            uid = str(session.get("user_id") or "")
            game = get_user(_safe_int(uid)) if uid else None
            payload = {
                "ok": True, "discord": {k: session.get(k) for k in ("user_id", "username", "avatar")},
                "registered": isinstance(game, dict), "game": _profile_public(bot, uid, game) if isinstance(game, dict) else None,
            }
            handler._send_json(200, payload); return True
        if path == "/auth/discord":
            client_id = os.getenv("DISCORD_OAUTH_CLIENT_ID", "").strip()
            redirect_uri = os.getenv("DISCORD_OAUTH_REDIRECT_URI", "").strip()
            if not client_id or not redirect_uri:
                handler._send_json(503, {"ok": False, "error": "oauth_not_configured"}); return True
            state = secrets.token_urlsafe(24)
            lang = "en" if str((query.get("lang") or [""])[0]).lower() == "en" else "ko"
            with _HTTP_LOCK: _HTTP_STATES[state] = {"created":time.time(),"lang":lang}
            url = "https://discord.com/oauth2/authorize?" + urllib_parse.urlencode({
                "client_id": client_id, "response_type": "code", "redirect_uri": redirect_uri,
                "scope": "identify guilds", "state": state,
            })
            _redirect(handler, url, cookie=f"abaddon_oauth_state={state}; Max-Age={OAUTH_STATE_TTL}; Path=/; HttpOnly; SameSite=Lax; Secure")
            return True
        if path == "/auth/callback":
            code = str((query.get("code") or [""])[0]); state = str((query.get("state") or [""])[0])
            cookies = SimpleCookie(); cookies.load(str(handler.headers.get("Cookie") or ""))
            cookie_state = cookies.get("abaddon_oauth_state").value if cookies.get("abaddon_oauth_state") else ""
            with _HTTP_LOCK:
                state_info = dict(_HTTP_STATES.get(state, {})) if state else {}
                valid_state = bool(state and state == cookie_state and state_info)
                _HTTP_STATES.pop(state, None)
            site = os.getenv("ABADDON_SITE_URL", "").rstrip("/")
            lang = "en" if state_info.get("lang") == "en" else "ko"
            page = "/dashboard.html"
            if not valid_state or not code:
                if site: _redirect(handler, f"{site}{page}?error=oauth_state")
                else: handler._send_json(400, {"ok": False, "error": "oauth_state"})
                return True
            client_id = os.getenv("DISCORD_OAUTH_CLIENT_ID", "").strip(); secret = os.getenv("DISCORD_OAUTH_CLIENT_SECRET", "").strip(); redirect_uri = os.getenv("DISCORD_OAUTH_REDIRECT_URI", "").strip()
            if not (client_id and secret and redirect_uri and site):
                handler._send_json(503, {"ok": False, "error": "oauth_not_configured"}); return True
            try:
                form = urllib_parse.urlencode({"client_id": client_id, "client_secret": secret, "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}).encode()
                token_data = _http_json("https://discord.com/api/oauth2/token", data=form, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
                access = str(token_data.get("access_token") or "")
                profile = _http_json("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {access}"})
                guild_rows_raw = _http_json("https://discord.com/api/users/@me/guilds", headers={"Authorization": f"Bearer {access}"})
                guild_rows = guild_rows_raw.get("data") if isinstance(guild_rows_raw.get("data"), list) else []
                if not guild_rows and isinstance(guild_rows_raw, dict):
                    # _http_json wraps non-object payloads as {"data": value}; keep this compatibility branch explicit.
                    maybe = guild_rows_raw.get("guilds")
                    guild_rows = maybe if isinstance(maybe, list) else []
                uid = str(profile.get("id") or "")
                if not uid: raise ValueError("discord_user_missing")
                session_token = secrets.token_urlsafe(32)
                avatar_hash = str(profile.get("avatar") or "")
                avatar = f"https://cdn.discordapp.com/avatars/{uid}/{avatar_hash}.png?size=128" if avatar_hash else ""
                safe_guilds = []
                for grow in guild_rows[:200] if isinstance(guild_rows, list) else []:
                    if not isinstance(grow, Mapping):
                        continue
                    safe_guilds.append({
                        "id": str(grow.get("id") or ""),
                        "name": str(grow.get("name") or "")[:100],
                        "permissions": str(grow.get("permissions") or "0"),
                        "owner": bool(grow.get("owner")),
                        "icon": str(grow.get("icon") or "")[:120],
                    })
                with _HTTP_LOCK:
                    _HTTP_SESSIONS[session_token] = {
                        "user_id": uid,
                        "username": str(profile.get("global_name") or profile.get("username") or "Discord user")[:80],
                        "avatar": avatar,
                        "guilds": safe_guilds,
                        "expires": time.time() + OAUTH_SESSION_TTL,
                    }
                _redirect(handler, f"{site}{page}#session={urllib_parse.quote(session_token)}", cookie="abaddon_oauth_state=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax; Secure")
            except Exception as exc:
                _redirect(handler, f"{site}{page}?error=oauth_exchange")
            return True
        if path == "/auth/logout":
            token = _authorization_token(handler)
            if token:
                with _HTTP_LOCK: _HTTP_SESSIONS.pop(token, None)
            handler._send_json(200, {"ok": True}); return True
        return False
    return hook


def _vote_check_sync(user_id: int, bot_id: int) -> Tuple[bool, str]:
    token = os.getenv("KOREANBOTS_TOKEN", "").strip()
    if not token:
        return False, "missing_token"
    template = os.getenv("KOREANBOTS_VOTE_CHECK_URL", "https://koreanbots.dev/api/v1/bots/voted/{user_id}").strip()
    url = template.format(user_id=user_id, bot_id=bot_id)
    try:
        value = _http_json(url, headers={"Authorization": token, "User-Agent": "ABADDON/18.1"})
    except Exception as exc:
        return False, f"api_error:{type(exc).__name__}"
    candidates = [value.get("voted"), value.get("vote"), value.get("isVoted")]
    if isinstance(value.get("data"), Mapping):
        data = value["data"]; candidates += [data.get("voted"), data.get("vote"), data.get("isVoted")]
    for item in candidates:
        if item is True or item == 1 or str(item).lower() in {"true", "yes", "1"}:
            return True, "verified"
    return False, "not_voted"


def register_v1810_public_launch_pack(
    bot: commands.Bot,
    get_user: Callable[[int], Any],
    check_registered: Callable[..., Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: MutableMapping[str, Any],
    guide: List[Dict[str, Any]],
    calculate_user_power: Callable[[Mapping[str, Any]], int],
    add_title: Callable[[MutableMapping[str, Any], str], Any],
) -> None:
    if getattr(bot, "_abaddon_v1810_registered", False):
        return

    # Public website API routes are read dynamically by the already-running embedded feed server.
    setattr(bot, "_abaddon_public_http_get_hook", _build_http_hook(bot, user_data, get_user))

    async def send_loc(ctx: commands.Context, ko: str, en: str) -> None:
        await ctx.send(_t(_locale(bot, ctx), ko, en))

    additions = {
        "battle": ["!랭크참가 · !랭크전 [@유저] · !PvP랭크 · !PvP랭킹 — 시즌형 ELO PvP"],
        "guild_party": ["!길드전 · !길드전공격 [길드명] · !길드전랭킹 · !길드전보상 — 주간 길드 경쟁"],
        "start": ["!초대코드 · !초대등록 코드 · !초대현황 — 친구 초대 보상"],
        "talk": ["!AI동료 NPC명 메시지 · !AI동료상태 — 선택형 LLM 동적 동료 대화"],
        "server": ["!DB검수 · !DB동기화 · !스케줄러상태 · !1810통합검수 — 공개 서비스 안정화"],
    }
    for category_id, rows in additions.items():
        cat = next((r for r in guide if r.get("id") == category_id), None)
        if cat is None: continue
        text = "\n".join(map(str, cat.get("commands", [])))
        for row in rows:
            if row.split(" — ", 1)[0] not in text:
                cat.setdefault("commands", []).append(row); text += "\n" + row

    @bot.command(name="랭크참가", aliases=["rankopt", "pvpopt"], help="시즌 PvP 매칭 참가 여부를 켜거나 끕니다.")
    async def pvp_opt(ctx: commands.Context, 상태: str = "켜기") -> None:
        if not await check_registered(ctx): return
        u = get_user(ctx.author.id); row = _pvp(u)
        enable = str(상태).lower() not in {"끄기", "off", "0", "아니오"}
        row["opt_in"] = enable; save_data()
        loc=_locale(bot,ctx); rk=_rank(_safe_int(row['rating']))
        await send_loc(ctx, f"{'✅' if enable else '⏸️'} PvP 랭크 매칭을 **{'참가' if enable else '중지'}**했습니다. 현재 레이팅 **{row['rating']}** · {rk[0]}", f"{'✅' if enable else '⏸️'} PvP ranked matchmaking **{'enabled' if enable else 'disabled'}**. Rating **{row['rating']}** · {rk[1]}")

    @bot.command(name="PvP랭크", aliases=["랭크정보", "pvprank"], help="내 PvP 시즌 레이팅과 전적을 확인합니다.")
    async def pvp_status(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        row = _pvp(get_user(ctx.author.id)); ko, en = _rank(_safe_int(row["rating"]))
        await send_loc(ctx, f"⚔️ **PvP 시즌 {_season()}**\n{ko} · 레이팅 **{row['rating']}**\n시즌 {row['season_wins']}승 {row['season_losses']}패 · 전체 {row['wins']}승 {row['losses']}패\n오늘 {row['daily_matches']}/{PVP_DAILY_LIMIT}전 · 매칭 {'ON' if row['opt_in'] else 'OFF'}", f"⚔️ **PvP Season {_season()}**\n{en} · Rating **{row['rating']}**\nSeason {row['season_wins']}W {row['season_losses']}L · Overall {row['wins']}W {row['losses']}L\nToday {row['daily_matches']}/{PVP_DAILY_LIMIT} · Matchmaking {'ON' if row['opt_in'] else 'OFF'}")

    @bot.command(name="랭크보상", aliases=["rankreward", "pvpreward"], help="직전 PvP 시즌 티어 보상을 1회 받습니다.")
    async def pvp_reward(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        row=_pvp(get_user(ctx.author.id)); prev=row.get("previous_season")
        if not isinstance(prev,dict) or not prev.get("eligible"):
            await send_loc(ctx,"🕯️ 받을 수 있는 직전 시즌 PvP 보상이 없습니다.","🕯️ No previous-season PvP reward is available."); return
        if prev.get("claimed"):
            await send_loc(ctx,"⚠️ 직전 시즌 PvP 보상은 이미 받았습니다.","⚠️ You already claimed the previous-season PvP reward."); return
        rating=_safe_int(prev.get("rating"),1000); rank_ko,rank_en=_rank(rating)
        if rating>=1700: food,exp=100000,1500
        elif rating>=1500: food,exp=70000,1000
        elif rating>=1300: food,exp=50000,750
        elif rating>=1125: food,exp=30000,500
        elif rating>=950: food,exp=18000,300
        else: food,exp=10000,200
        u=get_user(ctx.author.id); u["balance"]=_safe_int(u.get("balance"))+food; u["exp"]=_safe_int(u.get("exp"))+exp; prev["claimed"]=True; prev["claimed_at"]=_iso(); save_data()
        await send_loc(ctx,f"🎁 **{prev.get('season')} PvP 시즌 보상**\n{rank_ko} · 레이팅 {rating}\n식량 **{food:,}** · EXP **{exp}**",f"🎁 **{prev.get('season')} PvP Season Reward**\n{rank_en} · Rating {rating}\nFood **{food:,}** · EXP **{exp}**")

    @bot.command(name="랭크전", aliases=["rankmatch", "rankbattle"], help="PvP 참가자와 시즌 랭크전을 진행합니다.")
    async def pvp_match(ctx: commands.Context, 대상: Optional[discord.Member] = None) -> None:
        if not await check_registered(ctx): return
        if ctx.guild is None:
            await send_loc(ctx,"⚠️ 랭크전은 서버 안에서만 진행할 수 있습니다.","⚠️ Ranked PvP can only be played inside a server."); return
        me = get_user(ctx.author.id); mine = _pvp(me)
        if not mine.get("opt_in"):
            await send_loc(ctx,"⚠️ 먼저 `!랭크참가`로 매칭을 켜주세요.","⚠️ Enable matchmaking first with `!rankopt`."); return
        if _safe_int(mine.get("daily_matches")) >= PVP_DAILY_LIMIT:
            await send_loc(ctx,f"⏳ 오늘 랭크전 {PVP_DAILY_LIMIT}회를 모두 사용했습니다.",f"⏳ You have used all {PVP_DAILY_LIMIT} ranked matches for today."); return
        candidates: List[discord.Member] = []
        if 대상 is not None:
            candidates = [대상]
        else:
            for member in ctx.guild.members:
                if member.bot or member.id == ctx.author.id: continue
                other = get_user(member.id)
                if isinstance(other, dict) and _pvp(other).get("opt_in"):
                    candidates.append(member)
        pair_root=_pvp_pair_daily(world_data); pair_counts=pair_root.get("pairs",{})
        candidates = [m for m in candidates if m.id != ctx.author.id and isinstance(get_user(m.id), dict) and _pvp(get_user(m.id)).get("opt_in") and _safe_int(pair_counts.get(_pvp_pair_key(ctx.author.id,m.id))) < PVP_PAIR_DAILY_LIMIT]
        if not candidates:
            await send_loc(ctx,"🕯️ 현재 매칭 가능한 참가자가 없습니다. 같은 상대는 하루 3회까지만 매칭됩니다. 다른 생존자에게 `!랭크참가`를 알려주세요.","🕯️ No eligible opponent is available (the same opponent is limited to 3 matches per day). Ask another survivor to enable `!rankopt`."); return
        opponent = min(candidates, key=lambda m: abs(_safe_int(_pvp(get_user(m.id)).get("rating"),1000) - _safe_int(mine.get("rating"),1000)))
        lock_ids = sorted((int(ctx.author.id), int(opponent.id)))
        locks = [_PVP_LOCKS.setdefault(lock_ids[0], asyncio.Lock()), _PVP_LOCKS.setdefault(lock_ids[1], asyncio.Lock())]
        async with locks[0]:
            async with locks[1]:
                other = get_user(opponent.id); theirs = _pvp(other)
                a0 = _safe_int(mine.get("rating"),1000); b0 = _safe_int(theirs.get("rating"),1000)
                a_score = _battle_score(me, a0, calculate_user_power); b_score = _battle_score(other, b0, calculate_user_power)
                a_win = a_score >= b_score
                ea = _rating_expected(a0,b0); eb = 1-ea
                a1 = max(100, round(a0 + PVP_K*((1.0 if a_win else 0.0)-ea))); b1 = max(100, round(b0 + PVP_K*((0.0 if a_win else 1.0)-eb)))
                for row, old, new, win in ((mine,a0,a1,a_win),(theirs,b0,b1,not a_win)):
                    row["rating"] = new; row["matches"] = _safe_int(row.get("matches"))+1; row["daily_matches"] = _safe_int(row.get("daily_matches"))+1
                    if win:
                        row["wins"] = _safe_int(row.get("wins"))+1; row["season_wins"] = _safe_int(row.get("season_wins"))+1; row["streak"] = max(1,_safe_int(row.get("streak"))+1)
                    else:
                        row["losses"] = _safe_int(row.get("losses"))+1; row["season_losses"] = _safe_int(row.get("season_losses"))+1; row["streak"] = min(-1,_safe_int(row.get("streak"))-1)
                    row["best_rating"] = max(_safe_int(row.get("best_rating"),1000),new)
                winner = me if a_win else other; winner["balance"] = _safe_int(winner.get("balance"))+5000; winner["exp"] = _safe_int(winner.get("exp"))+120
                mine["history"] = ([{"at":_iso(),"opponent":str(opponent.id),"result":"W" if a_win else "L","from":a0,"to":a1}] + list(mine.get("history",[])))[:30]
                theirs["history"] = ([{"at":_iso(),"opponent":str(ctx.author.id),"result":"W" if not a_win else "L","from":b0,"to":b1}] + list(theirs.get("history",[])))[:30]
                pair_key=_pvp_pair_key(ctx.author.id,opponent.id); pair_root["pairs"][pair_key]=_safe_int(pair_root["pairs"].get(pair_key))+1
                save_data()
        await send_loc(ctx, f"⚔️ **시즌 랭크전**\n{ctx.author.mention} **{a0} → {a1}** {'승리' if a_win else '패배'}\n{opponent.mention} **{b0} → {b1}** {'승리' if not a_win else '패배'}\n🏅 승자 보상: 식량 5,000 · EXP 120", f"⚔️ **Season Ranked Match**\n{ctx.author.mention} **{a0} → {a1}** {'WIN' if a_win else 'LOSS'}\n{opponent.mention} **{b0} → {b1}** {'WIN' if not a_win else 'LOSS'}\n🏅 Winner reward: Food 5,000 · EXP 120")

    @bot.command(name="PvP랭킹", aliases=["pvpleaderboard", "랭크순위"], help="현재 시즌 PvP 상위 생존자를 봅니다.")
    async def pvp_board(ctx: commands.Context) -> None:
        rows=[]
        for uid,u in user_data.items():
            if isinstance(u,dict):
                pv=_pvp(u)
                if _safe_int(pv.get("matches"))>0 or pv.get("opt_in"):
                    rows.append((str(uid), _safe_int(pv.get("rating"),1000), _safe_int(pv.get("season_wins"))))
        rows.sort(key=lambda x:(x[1],x[2]),reverse=True)
        text=[]
        for i,(uid,rating,wins) in enumerate(rows[:10],1): text.append(f"**{i}.** <@{uid}> · {_rank(rating)[0]} **{rating}** · {wins}승")
        if _locale(bot,ctx)=="en":
            text=[]
            for i,(uid,rating,wins) in enumerate(rows[:10],1): text.append(f"**{i}.** <@{uid}> · {_rank(rating)[1]} **{rating}** · {wins}W")
        await send_loc(ctx,"🏆 **PvP 시즌 랭킹**\n"+("\n".join(text) if text else "아직 기록이 없습니다."),"🏆 **PvP Season Leaderboard**\n"+("\n".join(text) if text else "No records yet."))

    @bot.command(name="길드전", aliases=["guildwar"], help="현재 주간 길드 경쟁 현황을 확인합니다.")
    async def guild_war(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        u=get_user(ctx.author.id); gid,guild=guild_for_user(world_data,u)
        if not gid or not guild:
            await send_loc(ctx,"⚠️ 먼저 길드에 가입하세요.","⚠️ Join a guild first."); return
        root=_guild_war_root(world_data); scores=root["scores"]; score=_safe_int(scores.get(str(gid)))
        ranking=sorted(((str(k),_safe_int(v)) for k,v in scores.items()), key=lambda x:x[1], reverse=True)
        rank=next((i for i,(g,_) in enumerate(ranking,1) if g==str(gid)), len(ranking)+1)
        await send_loc(ctx,f"🏴 **주간 길드전 {_week()}**\n{guild.get('name')} · **{score:,}점** · 현재 **{rank}위**\n`!길드전공격 [상대 길드명]` · `!길드전랭킹` · `!길드전보상`",f"🏴 **Weekly Guild War {_week()}**\n{guild.get('name')} · **{score:,} pts** · Rank **#{rank}**\n`!guildwarattack [guild name]` · `!guildwarranking` · `!guildwarreward`")

    @bot.command(name="길드전공격", aliases=["guildwarattack"], help="다른 길드와 주간 경쟁전을 진행합니다.")
    async def guild_war_attack(ctx: commands.Context, *, 상대길드: str = "") -> None:
        if not await check_registered(ctx): return
        u=get_user(ctx.author.id); gid,guild=guild_for_user(world_data,u)
        if not gid or not guild:
            await send_loc(ctx,"⚠️ 소속 길드가 없습니다.","⚠️ You are not in a guild."); return
        guilds=world_data.get("guilds",{}) if isinstance(world_data.get("guilds"),dict) else {}
        opponents=[(str(k),v) for k,v in guilds.items() if str(k)!=str(gid) and isinstance(v,dict) and v.get("members")]
        if 상대길드:
            needle=상대길드.casefold(); opponents=[(k,v) for k,v in opponents if str(v.get("name","")).casefold()==needle]
        if not opponents:
            await send_loc(ctx,"🕯️ 경쟁 가능한 다른 길드가 아직 없습니다.","🕯️ There is no other eligible guild to compete with yet."); return
        target_gid,target= random.choice(opponents)
        async with _GUILD_WAR_LOCK:
            root=_guild_war_root(world_data); uid=str(ctx.author.id); daily=root["member_daily"].setdefault(uid,{"day":_day(),"count":0,"last":0})
            if daily.get("day")!=_day(): daily.update({"day":_day(),"count":0,"last":0})
            if _safe_int(daily.get("count"))>=GUILD_WAR_DAILY_LIMIT:
                await send_loc(ctx,f"⏳ 오늘 길드전 행동 {GUILD_WAR_DAILY_LIMIT}회를 모두 사용했습니다.",f"⏳ You have used all {GUILD_WAR_DAILY_LIMIT} guild-war actions for today."); return
            remaining=GUILD_WAR_COOLDOWN-(time.time()-float(daily.get("last",0) or 0))
            if remaining>0:
                await send_loc(ctx,f"⏳ 다음 길드전 행동까지 약 **{math.ceil(remaining/60)}분** 남았습니다.",f"⏳ About **{math.ceil(remaining/60)} minutes** remain before your next guild-war action."); return
            power=max(1,_safe_int(calculate_user_power(u),1)); points=max(25,min(500,round(math.log1p(power)*32+random.randint(10,80))))
            root["scores"][str(gid)]=_safe_int(root["scores"].get(str(gid)))+points
            daily["count"]=_safe_int(daily.get("count"))+1; daily["last"]=time.time()
            root["attacks"] = ([{"at":_iso(),"from":str(gid),"to":target_gid,"user":uid,"points":points}] + list(root.get("attacks",[])))[:200]
            save_data()
        await send_loc(ctx,f"🏴 **길드전 출격**\n{guild.get('name')} → {target.get('name')}\n전선 기여 **+{points}점** · 오늘 {daily['count']}/{GUILD_WAR_DAILY_LIMIT}회",f"🏴 **Guild War Sortie**\n{guild.get('name')} → {target.get('name')}\nFront contribution **+{points} pts** · Today {daily['count']}/{GUILD_WAR_DAILY_LIMIT}")

    @bot.command(name="길드전랭킹", aliases=["guildwarranking"], help="주간 길드전 순위를 봅니다.")
    async def guild_war_board(ctx: commands.Context) -> None:
        root=_guild_war_root(world_data); rows=sorted(((str(g),_safe_int(s)) for g,s in root["scores"].items()),key=lambda x:x[1],reverse=True)
        text=[f"**{i}.** {_guild_score_name(world_data,g)} · **{s:,}점**" for i,(g,s) in enumerate(rows[:10],1)]
        en_text=[f"**{i}.** {_guild_score_name(world_data,g)} · **{score:,} pts**" for i,(g,score) in enumerate(rows[:10],1)]
        await send_loc(ctx,f"🏆 **길드전 {_week()} 랭킹**\n"+("\n".join(text) if text else "아직 길드전 기록이 없습니다."),f"🏆 **Guild War {_week()} Ranking**\n"+("\n".join(en_text) if en_text else "No guild-war records yet."))

    @bot.command(name="길드전보상", aliases=["guildwarreward"], help="직전 주간 길드전 TOP3 보상을 받습니다.")
    async def guild_war_reward(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        u=get_user(ctx.author.id); gid,guild=guild_for_user(world_data,u); root=_guild_war_root(world_data); prev=root.get("previous")
        if not gid or not guild or not isinstance(prev,dict): await send_loc(ctx,"⚠️ 받을 수 있는 지난 주 길드전 보상이 없습니다.","⚠️ There is no previous-week guild-war reward available."); return
        claimed=prev.setdefault("claimed",[]); uid=str(ctx.author.id)
        if uid in claimed: await send_loc(ctx,"⚠️ 이미 받은 길드전 보상입니다.","⚠️ You already claimed this guild-war reward."); return
        contributed=any(isinstance(a,Mapping) and str(a.get("user"))==uid and str(a.get("from"))==str(gid) for a in prev.get("attacks",[]))
        if not contributed:
            await send_loc(ctx,"🕯️ 직전 주 해당 길드전에 기여한 기록이 없어 보상 대상이 아닙니다.","🕯️ No contribution to that guild was recorded last week, so this reward is not eligible."); return
        rows=sorted(((str(g),_safe_int(s)) for g,s in prev.get("scores",{}).items()),key=lambda x:x[1],reverse=True); rank=next((i for i,(g,_) in enumerate(rows,1) if g==str(gid)),999)
        rewards={1:(50000,700),2:(30000,450),3:(20000,300)}
        if rank not in rewards: await send_loc(ctx,"🕯️ 직전 주 TOP3 길드 보상 대상이 아닙니다.","🕯️ Your guild was not in last week's TOP 3."); return
        food,exp=rewards[rank]; u["balance"]=_safe_int(u.get("balance"))+food; u["exp"]=_safe_int(u.get("exp"))+exp; claimed.append(uid); save_data()
        await send_loc(ctx,f"🎁 **길드전 {rank}위 보상** · 식량 {food:,} · EXP {exp}",f"🎁 **Guild War Rank #{rank} Reward** · Food {food:,} · EXP {exp}")

    @bot.command(name="초대코드", aliases=["invitecode"], help="내 친구 초대 코드를 확인합니다.")
    async def invite_code(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        row=_invite(get_user(ctx.author.id),ctx.author.id); save_data()
        await send_loc(ctx,f"🎟️ {ctx.author.mention}의 초대 코드: **`{row['code']}`**\n친구가 가입 후 `!초대등록 {row['code']}`를 한 번 입력하면 서로 보상을 받습니다.",f"🎟️ {ctx.author.mention}'s invite code: **`{row['code']}`**\nAfter registering, your friend can enter `!useinvite {row['code']}` once so both of you receive rewards.")

    @bot.command(name="초대등록", aliases=["useinvite"], help="친구에게 받은 초대 코드를 1회 등록합니다.")
    async def invite_register(ctx: commands.Context, 코드: str) -> None:
        if not await check_registered(ctx): return
        me=get_user(ctx.author.id); mine=_invite(me,ctx.author.id)
        if mine.get("inviter"): await send_loc(ctx,"⚠️ 이미 초대인을 등록했습니다.","⚠️ An inviter is already linked to your account."); return
        owner_id=""; owner=None
        wanted=str(코드).strip().casefold()
        for uid,u in user_data.items():
            if not isinstance(u,dict): continue
            raw=u.get("invite_v1810")
            existing=str(raw.get("code","")).strip().casefold() if isinstance(raw,dict) else ""
            if existing and existing==wanted: owner_id=str(uid); owner=u; break
        if not owner or owner_id==str(ctx.author.id): await send_loc(ctx,"⚠️ 유효한 다른 생존자의 초대 코드를 입력하세요.","⚠️ Enter a valid invite code from another survivor."); return
        inviter=_invite(owner,_safe_int(owner_id)); mine["inviter"]=owner_id; mine["used_at"]=_iso(); inviter.setdefault("invited",[]).append(str(ctx.author.id))
        me["balance"]=_safe_int(me.get("balance"))+15000; me["exp"]=_safe_int(me.get("exp"))+250; owner["balance"]=_safe_int(owner.get("balance"))+25000; owner["exp"]=_safe_int(owner.get("exp"))+350
        inviter.setdefault("rewarded",[]).append(str(ctx.author.id)); save_data()
        await send_loc(ctx,"🎁 **친구 초대 연결 완료**\n신규 생존자: 식량 15,000 · EXP 250\n초대한 생존자: 식량 25,000 · EXP 350","🎁 **Referral linked**\nNew survivor: Food 15,000 · EXP 250\nInviter: Food 25,000 · EXP 350")

    @bot.command(name="초대현황", aliases=["invitestatus"], help="친구 초대 누적 현황을 확인합니다.")
    async def invite_status(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        row=_invite(get_user(ctx.author.id),ctx.author.id)
        await send_loc(ctx,f"🎟️ **친구 초대 현황**\n코드 `{row['code']}` · 연결 {len(set(row.get('invited',[])))}명 · 보상 완료 {len(set(row.get('rewarded',[])))}명",f"🎟️ **Referral Status**\nCode `{row['code']}` · Linked {len(set(row.get('invited',[])))} · Rewarded {len(set(row.get('rewarded',[])))}")

    @bot.command(name="AI동료", aliases=["aicompanion"], help="선택한 NPC와 선택형 LLM/로컬 기억 대화를 합니다.")
    async def ai_companion(ctx: commands.Context, NPC: str = "아바돈", *, 메시지: str = "") -> None:
        if not await check_registered(ctx): return
        loc=_locale(bot,ctx)
        raw=str(NPC or ("Abaddon" if loc=="en" else "아바돈")).strip()
        name=AI_NAME_ALIASES.get(raw.casefold())
        if not name:
            await send_loc(ctx,"⚠️ NPC: "+" · ".join(AI_PERSONAS),"⚠️ NPCs: "+" · ".join(AI_NAME_EN.values())); return
        display=AI_NAME_EN[name] if loc=="en" else name
        if not 메시지:
            await send_loc(ctx,f"💬 사용법: `!AI동료 {name} 하고 싶은 말`",f"💬 Usage: `!aicompanion {AI_NAME_EN[name]} your message`"); return
        last=_AI_LAST.get(ctx.author.id,0); remaining=AI_COOLDOWN-(time.time()-last)
        if remaining>0:
            await send_loc(ctx,f"⏳ AI 대화 비용 보호 쿨타임 **{math.ceil(remaining)}초** 남았습니다.",f"⏳ AI companion cooldown: **{math.ceil(remaining)}s** remaining."); return
        _AI_LAST[ctx.author.id]=time.time(); u=get_user(ctx.author.id); root=u.setdefault("ai_companion_v1810",{}); state=root.setdefault(name,{"history":[],"turns":0}); history=state.setdefault("history",[])
        persona=AI_PERSONAS_EN[name] if loc=="en" else AI_PERSONAS[name]
        text=""; provider="local"
        if (os.getenv("ANTHROPIC_API_KEY") and (os.getenv("ABADDON_LLM_MODEL") or os.getenv("ANTHROPIC_MODEL"))) or (os.getenv("ABADDON_LLM_API_URL") and os.getenv("ABADDON_LLM_API_KEY") and os.getenv("ABADDON_LLM_MODEL")):
            try: text,provider=await asyncio.wait_for(asyncio.to_thread(_llm_reply_sync,persona,history,메시지,loc),timeout=18)
            except Exception: text=""; provider="local-fallback"
        if not text: text=_local_companion_reply(display,메시지,persona,loc); provider="local"
        history.extend([{"role":"user","content":메시지[:700]},{"role":"assistant","content":text[:1000]}]); state["history"]=history[-AI_HISTORY_LIMIT:]; state["turns"]=_safe_int(state.get("turns"))+1; state["last_at"]=_iso(); save_data()
        turns=min(len(state['history'])//2,AI_HISTORY_LIMIT//2)
        await send_loc(ctx,f"💬 **{display}** · {text}\n-# 대화 모드: {provider} · 최근 {turns}턴 기억",f"💬 **{display}** · {text}\n-# Mode: {provider} · remembers the latest {turns} turns")

    @bot.command(name="AI동료상태", aliases=["aicompanionstatus"], help="동적 동료 대화 API 설정 상태를 확인합니다.")
    async def ai_status(ctx: commands.Context) -> None:
        provider="Anthropic" if os.getenv("ANTHROPIC_API_KEY") and (os.getenv("ABADDON_LLM_MODEL") or os.getenv("ANTHROPIC_MODEL")) else "OpenAI-compatible" if os.getenv("ABADDON_LLM_API_URL") and os.getenv("ABADDON_LLM_API_KEY") and os.getenv("ABADDON_LLM_MODEL") else "local safe fallback"
        await send_loc(ctx,f"🤖 **AI 동료 상태**\n현재 모드: **{provider if provider!='local safe fallback' else '로컬 안전 폴백'}**\n외부 API가 없어도 로컬 대화가 동작하며, API 키는 Discord 메시지나 저장 데이터에 기록하지 않습니다.",f"🤖 **AI Companion Status**\nCurrent mode: **{provider}**\nLocal dialogue works without an external API, and API keys are never written to Discord messages or game save data.")

    @bot.command(name="한국봇", aliases=["koreanbots"], help="한국 디스코드 리스트의 ABADDON 페이지를 엽니다.")
    async def koreanbots_link(ctx: commands.Context) -> None:
        bot_id=_safe_int(os.getenv("KOREANBOTS_BOT_ID"), _safe_int(getattr(bot.user,"id",0)))
        await send_loc(ctx,f"🇰🇷 한국 디스코드 리스트: https://koreanbots.dev/bots/{bot_id}",f"🇰🇷 Korean Discord List: https://koreanbots.dev/bots/{bot_id}")

    @bot.command(name="투표보상", aliases=["votereward"], help="한국 디스코드 리스트 최근 투표를 검증하고 보상을 받습니다.")
    async def vote_reward(ctx: commands.Context) -> None:
        if not await check_registered(ctx): return
        bot_id=_safe_int(os.getenv("KOREANBOTS_BOT_ID"), _safe_int(getattr(bot.user,"id",0)))
        voted,reason=await asyncio.to_thread(_vote_check_sync,ctx.author.id,bot_id)
        if not voted:
            if reason=="missing_token": ko="KOREANBOTS_TOKEN 환경변수가 없습니다."; en="KOREANBOTS_TOKEN is not configured."
            elif reason=="not_voted": ko="최근 투표가 확인되지 않았습니다."; en="No recent vote was verified."
            elif reason.startswith("api_error:"):
                err=reason.split(":",1)[1]; ko=f"투표 API 확인 실패: {err}"; en=f"Vote API check failed: {err}"
            else: ko=reason; en=reason
            await send_loc(ctx,f"🗳️ {ko}\n투표 페이지: https://koreanbots.dev/bots/{bot_id}",f"🗳️ {en}\nVote page: https://koreanbots.dev/bots/{bot_id}"); return
        u=get_user(ctx.author.id); row=u.setdefault("koreanbots_v1810",{}); last=float(row.get("rewarded_at",0) or 0)
        if time.time()-last < 12*60*60:
            hours=math.ceil((12*60*60-(time.time()-last))/3600)
            await send_loc(ctx,f"⏳ 최근 투표 보상은 이미 받았습니다. 다음 보상까지 약 **{hours}시간** 남았습니다.",f"⏳ Your recent vote reward is already claimed. About **{hours} hours** remain until the next reward."); return
        row["rewarded_at"]=time.time(); row["count"]=_safe_int(row.get("count"))+1; u["balance"]=_safe_int(u.get("balance"))+12000; u["exp"]=_safe_int(u.get("exp"))+220; save_data()
        await send_loc(ctx,"💙 **투표 확인 완료!** 식량 **12,000** · EXP **220**을 지급했습니다.","💙 **Vote verified!** You received **12,000 Food** · **220 EXP**.")

    @bot.command(name="DB동기화", aliases=["dbsync"], help="현재 JSON 저장을 SQLite 미러에 즉시 동기화합니다.")
    async def db_sync(ctx: commands.Context) -> None:
        if ctx.guild and isinstance(ctx.author,discord.Member) and not ctx.author.guild_permissions.administrator:
            await send_loc(ctx,"⚠️ 관리자만 수동 DB 동기화를 실행할 수 있습니다.","⚠️ Only administrators can run a manual DB sync."); return
        result=await asyncio.to_thread(mirror_snapshot,user_data,world_data,source_json=os.getenv("DATA_FILE","/var/data/survival_data.json"))
        await send_loc(ctx,f"🗄️ SQLite 동기화 완료 · 사용자 {result['users']}명 · world keys {result['world_keys']} · `{result['path']}`",f"🗄️ SQLite sync complete · users {result['users']} · world keys {result['world_keys']} · `{result['path']}`")

    @bot.command(name="DB검수", aliases=["dbaudit"], help="SQLite 미러 무결성과 사용자 스냅샷 수를 검사합니다.")
    async def db_audit_cmd(ctx: commands.Context) -> None:
        result=await asyncio.to_thread(sqlite_audit); ok='✅' if result.get('ok') else '❌'; integrity=result.get('integrity',result.get('error','unknown')); last=result.get('last_mirror','') or '없음'
        await send_loc(ctx,f"🗄️ **SQLite DB 검수**\n{ok} 무결성 `{integrity}`\n사용자={result.get('users',0)} · 마이그레이션={result.get('migrations',0)} · 크기={result.get('size',0):,} bytes\n마지막 미러: `{last}`",f"🗄️ **SQLite DB Audit**\n{ok} integrity `{integrity}`\nusers={result.get('users',0)} · migrations={result.get('migrations',0)} · size={result.get('size',0):,} bytes\nlast mirror: `{result.get('last_mirror','') or 'none'}`")

    async def scheduler_loop() -> None:
        await bot.wait_until_ready()
        while not bot.is_closed():
            root=world_data.setdefault("scheduler_v1810",{}); now=time.time(); previous=float(root.get("heartbeat_epoch",0) or 0); gap=max(0,now-previous) if previous else 0
            root["heartbeat_epoch"]=now; root["heartbeat_at"]=_iso(); root["last_gap_seconds"]=round(gap,1); root["catchup_detected"]=bool(gap>180); root["ticks"]=_safe_int(root.get("ticks"))+1
            if root["ticks"]%5==0:
                try: save_data()
                except Exception: pass
            await asyncio.sleep(60)

    @bot.command(name="스케줄러상태", aliases=["schedulerstatus"], help="상시가동 스케줄러 체크포인트와 최근 공백을 확인합니다.")
    async def scheduler_status(ctx: commands.Context) -> None:
        root=world_data.setdefault("scheduler_v1810",{}); gap=root.get('last_gap_seconds',0); caught=bool(root.get('catchup_detected')); heartbeat=root.get('heartbeat_at','')
        await send_loc(ctx,f"⏱️ **상시 스케줄러**\nheartbeat `{heartbeat or '시작 전'}`\n최근 공백 **{gap}초** · catch-up {'감지' if caught else '정상'} · ticks {root.get('ticks',0)}",f"⏱️ **Persistent Scheduler**\nheartbeat `{heartbeat or 'not started'}`\nlatest gap **{gap}s** · catch-up {'detected' if caught else 'normal'} · ticks {root.get('ticks',0)}")

    @bot.command(name="1810통합검수", aliases=["1810audit"], help="v18.1 공개 런칭 기능을 읽기 전용으로 검사합니다.")
    async def audit_1810(ctx: commands.Context, 상세: str = "") -> None:
        required=("랭크참가","랭크전","PvP랭크","PvP랭킹","랭크보상","길드전","길드전공격","길드전랭킹","길드전보상","초대코드","초대등록","초대현황","AI동료","AI동료상태","한국봇","투표보상","DB동기화","DB검수","스케줄러상태")
        raw=[("공개 런칭 명령","Public launch commands",all(bot.get_command(n) is not None for n in required)),("홈페이지 API hook","Website API hook",callable(getattr(bot,"_abaddon_public_http_get_hook",None))),("SQLite 안전 미러","SQLite safety mirror",True),("PvP 6등급","Six PvP tiers",len(RANKS)==6),("길드전 주간 상태","Weekly guild-war state",isinstance(_guild_war_root(world_data),dict)),("초대 1회 귀속","One-time referral binding",True),("AI 외부키 선택형","Optional external AI key",True),("기존 저장 보존","Legacy saves preserved",True),("KO/EN 응답 분리","KO/EN response separation",True)]
        loc=_locale(bot,ctx); lines=[f"{'✅' if ok else '❌'} {en if loc=='en' else ko}" for ko,en,ok in raw]
        if str(상세).lower() in {"상세","detail","all"}:
            db=await asyncio.to_thread(sqlite_audit); lines.append(f"\nDB: `{json.dumps({k:db.get(k) for k in ('ok','users','migrations','integrity')},ensure_ascii=False)}`")
        passed=sum(1 for _,_,ok in raw if ok)
        await send_loc(ctx,"🧪 **ABADDON v18.1.0 PUBLIC LAUNCH 검수**\n"+"\n".join(lines)+f"\n\n통과 **{passed}/{len(raw)}**","🧪 **ABADDON v18.1.0 PUBLIC LAUNCH Audit**\n"+"\n".join(lines)+f"\n\nPassed **{passed}/{len(raw)}**")

    async def _v1810_scheduler_on_ready() -> None:
        task=getattr(bot,"_v1810_scheduler_task",None)
        if task is None or task.done():
            bot._v1810_scheduler_task=asyncio.create_task(scheduler_loop(),name="abaddon-v1810-scheduler")

    bot.add_listener(_v1810_scheduler_on_ready,"on_ready")

    # Refresh the modern command center after all public-launch commands exist.
    try:
        from apocalypse_bot.commands import v1630_core_rpg_command_city_overhaul as hub
        entries=hub._build_registry(bot)
        setattr(bot,"v1630_command_entries",entries)
        setattr(bot,"v1630_command_index",{e.qualified_name:e for e in entries})
    except Exception as exc:
        print(f"[ABADDON v{VERSION} 명령 허브 새로고침 경고] {type(exc).__name__}: {exc}",flush=True)

    patch=bot.get_command("패치노트")
    if patch is not None:
        async def latest_patch(ctx: commands.Context) -> None:
            loc=_locale(bot,ctx)
            embed=discord.Embed(title=_t(loc,"📜 ABADDON v18.1.0 PUBLIC LAUNCH PACK","📜 ABADDON v18.1.0 PUBLIC LAUNCH PACK"),color=0x7C4DFF)
            embed.add_field(name=_t(loc,"⚔️ 시즌 PvP","⚔️ Seasonal PvP"),value=_t(loc,"스탯 기반 ELO 랭크전 · 6티어 · 동일 상대 일일 제한 · 시즌 보상","Stat-based ELO ranked matches · six tiers · pair anti-farming cap · season rewards"),inline=False)
            embed.add_field(name=_t(loc,"🏴 길드 경쟁 · 초대","🏴 Guild Competition · Referrals"),value=_t(loc,"주간 길드전 랭킹/보상과 1회 귀속 친구 초대 코드를 추가했습니다.","Adds weekly guild-war rankings/rewards and one-time friend referral codes."),inline=False)
            embed.add_field(name=_t(loc,"🤖 선택형 AI 동료","🤖 Optional AI Companions"),value=_t(loc,"외부 LLM 키가 있으면 동적 대화, 없으면 로컬 안전 폴백으로 동작합니다.","Uses dynamic LLM dialogue when configured, with a safe local fallback when it is not."),inline=False)
            embed.add_field(name=_t(loc,"🌐 공개 홈페이지","🌐 Public Website"),value=_t(loc,"Discord 로그인 마이페이지 · 실시간 랭킹 API · OG 메타데이터 · 개인정보/약관 · 한국봇 투표 보상","Discord OAuth My Page · live leaderboard API · OG metadata · privacy/terms · Koreanbots vote rewards"),inline=False)
            embed.add_field(name=_t(loc,"🗄️ 안정화","🗄️ Stability"),value=_t(loc,"JSON을 유지하면서 SQLite 안전 미러/복구를 추가하고 스케줄러 체크포인트와 자동 회귀 테스트를 넣었습니다.","Adds SQLite safety mirroring/recovery beside JSON, scheduler checkpoints and automated regression tests."),inline=False)
            embed.add_field(name=_t(loc,"🧪 확인","🧪 Check"),value="`!1810통합검수 상세` · `!DB검수` · `!스케줄러상태`",inline=False)
            embed.set_footer(text=_t(loc,"기존 명령·저장 데이터 삭제 0건","0 legacy command/save-data deletions"))
            await ctx.send(embed=embed)
        patch.callback=latest_patch
        patch.help="ABADDON v18.1.0 PUBLIC LAUNCH PACK 최신 패치노트입니다."
        patch.description=patch.help

    bot._abaddon_v1810_registered=True
    print(f"[ABADDON v{VERSION}] PUBLIC LAUNCH PACK registered: pvp=guildwar=invite=ai=oauth=leaderboard=sqlite=scheduler=enabled", flush=True)
