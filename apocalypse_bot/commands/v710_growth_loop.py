from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import discord
from discord.ext import commands

VERSION = "7.1.0"
ROOT_KEY = "growth_loop_v710"
USER_KEY = "growth_v710"
KST = timezone(timedelta(hours=9))
ACTIVITY_COOLDOWN_SECONDS = 15
MAX_DAILY_COUNTED_ACTIONS = 20
MAX_PRESETS = 3

# 성공적으로 끝난 명령어만 집계합니다. 기존 명령은 그대로 두고 성장 루프에서 분류만 합니다.
ACTIVITY_COMMANDS: Mapping[str, frozenset[str]] = {
    # ctx.command.name의 실제 대표 명령명만 사용합니다. 별칭으로 실행해도 대표 이름으로 집계됩니다.
    "life": frozenset({
        "알바", "채집", "낚시", "벌목", "광산", "땅파기", "지역탐색", "탐색",
        "다크존탐색", "보급선수색", "기지수확", "까마귀", "펫모험",
    }),
    "combat": frozenset({
        "훈련", "던전", "심층던전", "전투", "레이드공격", "침공공격", "던전전술",
        "기지방어공격", "다크존공격", "괴질탈출", "영혼결투", "월드보스공격",
    }),
    "growth": frozenset({
        "구매", "장착", "강화", "보호강화", "제작", "무기수리", "무기개조", "개조부품제작",
        "펫훈련", "펫진화", "펫먹이", "기지건설", "기지강화", "옵션재설정", "장비프리셋",
    }),
    "signal": frozenset({
        "오늘의", "오늘의퀴즈", "서버브리핑", "날씨", "무전", "비상주파수", "오늘의질문",
    }),
    "worldboss": frozenset({"월드보스공격"}),
}

DAILY_TARGETS: Mapping[str, int] = {"life": 2, "combat": 2, "growth": 1, "signal": 1}
WEEKLY_TARGETS: Mapping[str, int] = {"life": 15, "combat": 15, "growth": 8, "signal": 5, "worldboss": 5, "daily_clear": 4}
WEEKLY_TIERS: Sequence[Tuple[int, int, int, Optional[str]]] = (
    (2, 15_000, 25, None),
    (4, 32_000, 45, "주간 작전 수행자"),
    (6, 65_000, 90, "주간 생존 루프 완주자"),
)
LIFETIME_MILESTONES: Sequence[Tuple[int, int, int, Optional[str]]] = (
    (20, 10_000, 1, None),
    (50, 22_000, 2, "꾸준한 생존자"),
    (100, 45_000, 3, None),
    (200, 90_000, 5, "황무지 루틴 전문가"),
    (400, 180_000, 8, "아바돈 장기 생존자"),
)

GROWTH_GUIDE = {
    "id": "growth_loop_v710",
    "emoji": "🌱",
    "title": "성장 루프 / 미션",
    "hint": "오늘 할 일, 일일·주간 미션, 누적 보상, 장비 프리셋, 월드보스 주간 랭킹",
    "commands": [
        "!오늘할일 — 이모지 진행률과 다음 추천 행동을 한 화면에서 확인",
        "!성장보드 — 일일·주간 미션·연속 달성·참여 점수 통합 확인",
        "!미션보상 — 완료한 일일 보상과 주간 단계 보상을 한 번에 수령",
        "!누적보상 — 누적 참여 점수의 성장 이정표 보상 수령",
        "!장비프리셋 — 레이드·생활·탐색용 장비 구성을 최대 3개 저장·적용",
        "!월드보스주간랭킹 — 이번 주 서버 월드보스 누적 피해 순위",
        "!월드보스주간보상 — 지난주 월드보스 순위 보상 수령",
        "!복귀보급 — 신규·장기 미접속 생존자 따라잡기 보급 확인",
    ],
}


def _now() -> datetime:
    return datetime.now(timezone.utc).astimezone(KST)


def _today() -> str:
    return _now().strftime("%Y-%m-%d")


def _week_key(moment: Optional[datetime] = None) -> str:
    point = (moment or _now()).astimezone(KST)
    year, week, _ = point.isocalendar()
    return f"{year}-W{week:02d}"


def _previous_week_key() -> str:
    return _week_key(_now() - timedelta(days=7))


def _safe_int(value: Any, default: int = 0, minimum: Optional[int] = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = int(default)
    if minimum is not None:
        result = max(minimum, result)
    return result


def _parse_iso(value: Any) -> Optional[datetime]:
    try:
        point = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if point.tzinfo is None:
        point = point.replace(tzinfo=timezone.utc)
    return point


def _bar(current: int, target: int, size: int = 10) -> str:
    target = max(1, _safe_int(target, 1, 1))
    current = max(0, _safe_int(current, 0, 0))
    ratio = min(1.0, current / target)
    filled = int(ratio * size)
    if current >= target:
        return "🟩" * size
    if filled <= 0:
        return "⬛" * size
    return "🟩" * filled + "🟨" + "⬛" * max(0, size - filled - 1)


def _task_line(label: str, current: int, target: int, command: str = "") -> str:
    complete = current >= target
    icon = "✅" if complete else "🟨" if current > 0 else "⬜"
    suffix = f" · `{command}`" if command else ""
    return f"{icon} **{label}**  {_bar(current, target, 6)}  `{min(current, target)}/{target}`{suffix}"


def _root(world_data: MutableMapping[str, Any]) -> Dict[str, Any]:
    root = world_data.setdefault(ROOT_KEY, {})
    if not isinstance(root, dict):
        root = {}
        world_data[ROOT_KEY] = root
    root.setdefault("version", VERSION)
    root.setdefault("guilds", {})
    if not isinstance(root.get("guilds"), dict):
        root["guilds"] = {}
    root["version"] = VERSION
    return root


def _guild_state(world_data: MutableMapping[str, Any], guild_id: int) -> Dict[str, Any]:
    root = _root(world_data)
    state = root["guilds"].setdefault(str(guild_id), {})
    if not isinstance(state, dict):
        state = {}
        root["guilds"][str(guild_id)] = state
    state.setdefault("worldboss_weekly", {})
    state.setdefault("worldboss_claimed", {})
    if not isinstance(state.get("worldboss_weekly"), dict):
        state["worldboss_weekly"] = {}
    if not isinstance(state.get("worldboss_claimed"), dict):
        state["worldboss_claimed"] = {}
    # 주차별 기록이 무한히 커지지 않도록 최근 16주만 유지합니다.
    for key in ("worldboss_weekly", "worldboss_claimed"):
        rows = state[key]
        for old_week in sorted(rows)[:-16]:
            rows.pop(old_week, None)
    return state


def _new_daily() -> Dict[str, Any]:
    return {
        "date": _today(),
        "counters": {"life": 0, "combat": 0, "growth": 0, "signal": 0, "worldboss": 0},
        "counted_actions": 0,
        "last_counted": {},
        "completed": False,
        "completed_at": "",
        "reward_claimed": False,
    }


def _new_weekly() -> Dict[str, Any]:
    return {
        "week": _week_key(),
        "counters": {"life": 0, "combat": 0, "growth": 0, "signal": 0, "worldboss": 0},
        "daily_clear_dates": [],
        "claimed_tiers": [],
    }


def _user_state(user: MutableMapping[str, Any]) -> Dict[str, Any]:
    state = user.setdefault(USER_KEY, {})
    if not isinstance(state, dict):
        state = {}
        user[USER_KEY] = state
    state.setdefault("version", VERSION)
    state.setdefault("daily", _new_daily())
    state.setdefault("weekly", _new_weekly())
    state.setdefault("lifetime", {})
    state.setdefault("presets", {})
    state.setdefault("support", {})
    if not isinstance(state.get("daily"), dict) or state["daily"].get("date") != _today():
        state["daily"] = _new_daily()
    if not isinstance(state.get("weekly"), dict) or state["weekly"].get("week") != _week_key():
        state["weekly"] = _new_weekly()
    if not isinstance(state.get("lifetime"), dict):
        state["lifetime"] = {}
    if not isinstance(state.get("presets"), dict):
        state["presets"] = {}
    if not isinstance(state.get("support"), dict):
        state["support"] = {}
    life = state["lifetime"]
    life.setdefault("participation", 0)
    life.setdefault("growth_marks", 0)
    life.setdefault("daily_clears", 0)
    life.setdefault("streak", 0)
    life.setdefault("best_streak", 0)
    life.setdefault("last_clear_date", "")
    life.setdefault("claimed_milestones", [])
    life.setdefault("last_seen_at", "")
    state["version"] = VERSION
    return state


def _is_attendance_done(user: Mapping[str, Any]) -> bool:
    return str(user.get("last_attendance", "")) == _today()


def _is_daily_quest_done(user: Mapping[str, Any]) -> bool:
    quest = user.get("daily_quest", {})
    return isinstance(quest, Mapping) and _safe_int(quest.get("target"), 1, 1) <= _safe_int(quest.get("progress"), 0, 0)


def _daily_status(user: MutableMapping[str, Any]) -> Tuple[Dict[str, bool], int]:
    state = _user_state(user)
    counters = state["daily"].setdefault("counters", {})
    flags = {
        "attendance": _is_attendance_done(user),
        "daily_quest": _is_daily_quest_done(user),
        "life": _safe_int(counters.get("life")) >= DAILY_TARGETS["life"],
        "combat": _safe_int(counters.get("combat")) >= DAILY_TARGETS["combat"],
        "growth": _safe_int(counters.get("growth")) >= DAILY_TARGETS["growth"],
        "signal": _safe_int(counters.get("signal")) >= DAILY_TARGETS["signal"],
    }
    return flags, sum(1 for value in flags.values() if value)


def _weekly_status(user: MutableMapping[str, Any]) -> Tuple[Dict[str, bool], int]:
    state = _user_state(user)
    weekly = state["weekly"]
    counters = weekly.setdefault("counters", {})
    values = {
        "life": _safe_int(counters.get("life")),
        "combat": _safe_int(counters.get("combat")),
        "growth": _safe_int(counters.get("growth")),
        "signal": _safe_int(counters.get("signal")),
        "worldboss": _safe_int(counters.get("worldboss")),
        "daily_clear": len(set(str(item) for item in weekly.get("daily_clear_dates", []))),
    }
    flags = {key: values[key] >= target for key, target in WEEKLY_TARGETS.items()}
    return flags, sum(1 for value in flags.values() if value)


def _sync_daily_clear(user: MutableMapping[str, Any]) -> bool:
    state = _user_state(user)
    daily = state["daily"]
    _, completed_count = _daily_status(user)
    # 6개 중 5개만 완료해도 일일 루프 완주. 초보자에게 한 기능을 건너뛸 여지를 줍니다.
    if completed_count < 5 or daily.get("completed"):
        return False
    daily["completed"] = True
    daily["completed_at"] = _now().isoformat()
    weekly = state["weekly"]
    dates = weekly.setdefault("daily_clear_dates", [])
    if _today() not in dates:
        dates.append(_today())
    life = state["lifetime"]
    previous = str(life.get("last_clear_date", ""))
    yesterday = (_now().date() - timedelta(days=1)).isoformat()
    life["streak"] = _safe_int(life.get("streak")) + 1 if previous == yesterday else 1
    life["best_streak"] = max(_safe_int(life.get("best_streak")), _safe_int(life.get("streak")))
    life["last_clear_date"] = _today()
    life["daily_clears"] = _safe_int(life.get("daily_clears")) + 1
    life["participation"] = _safe_int(life.get("participation")) + 5
    return True


def _touch_seen(state: Dict[str, Any]) -> None:
    life = state["lifetime"]
    previous = _parse_iso(life.get("last_seen_at"))
    support = state["support"]
    if previous is not None and _now() - previous.astimezone(KST) >= timedelta(days=14):
        support["return_eligible"] = True
        support["return_period"] = _today()
    life["last_seen_at"] = _now().isoformat()


def _record_activity(user: MutableMapping[str, Any], category: str, command_name: str) -> bool:
    state = _user_state(user)
    daily = state["daily"]
    if _safe_int(daily.get("counted_actions")) >= MAX_DAILY_COUNTED_ACTIONS:
        _touch_seen(state)
        return False
    now = _now()
    last_map = daily.setdefault("last_counted", {})
    last = _parse_iso(last_map.get(category))
    if last is not None and (now - last.astimezone(KST)).total_seconds() < ACTIVITY_COOLDOWN_SECONDS:
        _touch_seen(state)
        return False
    last_map[category] = now.isoformat()
    daily["counted_actions"] = _safe_int(daily.get("counted_actions")) + 1
    daily_counters = daily.setdefault("counters", {})
    weekly_counters = state["weekly"].setdefault("counters", {})
    daily_counters[category] = _safe_int(daily_counters.get(category)) + 1
    weekly_counters[category] = _safe_int(weekly_counters.get(category)) + 1
    if command_name == "월드보스공격":
        daily_counters["worldboss"] = max(1, _safe_int(daily_counters.get("worldboss")))
        weekly_counters["worldboss"] = _safe_int(weekly_counters.get("worldboss")) + (0 if category == "worldboss" else 1)
    life = state["lifetime"]
    life["participation"] = _safe_int(life.get("participation")) + 1
    _touch_seen(state)
    return True


def _find_category(command_name: str) -> Optional[str]:
    # 월드보스 공격은 실제 피해 계산이 끝난 시점의 전용 훅에서만 집계합니다.
    if command_name in ACTIVITY_COMMANDS["worldboss"]:
        return None
    for category in ("life", "combat", "growth", "signal"):
        if command_name in ACTIVITY_COMMANDS[category]:
            return category
    return None


def _activity_fingerprint(user: Mapping[str, Any], category: str) -> Tuple[Any, ...]:
    stats = user.get("stats", {}) if isinstance(user.get("stats"), Mapping) else {}
    resources = user.get("resources", {}) if isinstance(user.get("resources"), Mapping) else {}
    materials = user.get("materials", {}) if isinstance(user.get("materials"), Mapping) else {}
    equipment = user.get("equipment", {}) if isinstance(user.get("equipment"), Mapping) else {}
    enhancements = user.get("enhancements", {}) if isinstance(user.get("enhancements"), Mapping) else {}
    base = user.get("base", {}) if isinstance(user.get("base"), Mapping) else {}
    common = (
        _safe_int(user.get("balance")), _safe_int(user.get("level")), _safe_int(user.get("hp")),
        _safe_int(user.get("stamina")), _safe_int(user.get("infection")),
    )
    if category == "life":
        return common + (tuple(sorted((str(k), _safe_int(v)) for k, v in resources.items())), _safe_int(user.get("exploration_count")))
    if category == "combat":
        return common + tuple(_safe_int(stats.get(key)) for key in ("dungeon_wins", "dungeon_losses", "boss_damage", "worldboss_damage"))
    if category == "growth":
        return common + (
            tuple(sorted(str(item) for item in user.get("inventory", []) if item)),
            tuple(sorted((str(k), str(v)) for k, v in equipment.items())),
            tuple(sorted((str(k), _safe_int(v)) for k, v in enhancements.items())),
            tuple(sorted((str(k), _safe_int(v)) for k, v in materials.items())),
            tuple(sorted((str(k), str(v)) for k, v in base.items())),
            _safe_int(user.get("pet_level")),
        )
    return common


def _daily_lines(user: MutableMapping[str, Any]) -> List[str]:
    state = _user_state(user)
    counters = state["daily"].get("counters", {})
    return [
        _task_line("출석 신호", 1 if _is_attendance_done(user) else 0, 1, "!출석"),
        _task_line("기존 일일 퀘스트", 1 if _is_daily_quest_done(user) else 0, 1, "!일일퀘스트"),
        _task_line("생활 활동", _safe_int(counters.get("life")), DAILY_TARGETS["life"], "!채집 / !낚시 / !광산"),
        _task_line("전투 활동", _safe_int(counters.get("combat")), DAILY_TARGETS["combat"], "!던전 보통"),
        _task_line("성장 활동", _safe_int(counters.get("growth")), DAILY_TARGETS["growth"], "!강화 / !제작 / !장착"),
        _task_line("세계 신호 확인", _safe_int(counters.get("signal")), DAILY_TARGETS["signal"], "!오늘의운세 / !오늘의퀴즈"),
    ]


def _weekly_values(user: MutableMapping[str, Any]) -> Dict[str, int]:
    state = _user_state(user)
    counters = state["weekly"].get("counters", {})
    return {
        "life": _safe_int(counters.get("life")),
        "combat": _safe_int(counters.get("combat")),
        "growth": _safe_int(counters.get("growth")),
        "signal": _safe_int(counters.get("signal")),
        "worldboss": _safe_int(counters.get("worldboss")),
        "daily_clear": len(set(str(item) for item in state["weekly"].get("daily_clear_dates", []))),
    }


def _weekly_lines(user: MutableMapping[str, Any]) -> List[str]:
    values = _weekly_values(user)
    labels = {
        "life": "생활 작전",
        "combat": "전투 작전",
        "growth": "장비·성장",
        "signal": "세계 신호",
        "worldboss": "월드보스 참가",
        "daily_clear": "일일 루프 완주",
    }
    return [_task_line(labels[key], values[key], target) for key, target in WEEKLY_TARGETS.items()]


def _next_action(user: MutableMapping[str, Any]) -> Tuple[str, str]:
    flags, _ = _daily_status(user)
    if not flags["attendance"]:
        return "📅 출석부터 시작", "!출석"
    if not flags["daily_quest"]:
        return "🎯 기존 일일 퀘스트 진행", "!일일퀘스트"
    if not flags["life"]:
        return "🌿 생활 활동 2회", "!채집"
    if not flags["combat"]:
        return "⚔️ 전투 활동 2회", "!던전 보통"
    if not flags["growth"]:
        return "🔧 장비 성장 1회", "!장착"
    if not flags["signal"]:
        return "📡 세계 신호 확인", "!오늘의운세"
    state = _user_state(user)
    if state["daily"].get("completed") and not state["daily"].get("reward_claimed"):
        return "🎁 일일 루프 보상 수령", "!미션보상"
    return "🌋 선택 보너스: 월드보스 참가", "!월드보스"


def _apply_reward(
    user: MutableMapping[str, Any],
    food: int,
    marks: int,
    season_points: int,
    add_season_points: Callable[[MutableMapping[str, Any], int], None],
) -> None:
    user["balance"] = _safe_int(user.get("balance"), 0, 0) + max(0, food)
    stats = user.setdefault("stats", {})
    if isinstance(stats, dict):
        stats["earned"] = _safe_int(stats.get("earned"), 0, 0) + max(0, food)
    state = _user_state(user)
    state["lifetime"]["growth_marks"] = _safe_int(state["lifetime"].get("growth_marks")) + max(0, marks)
    add_season_points(user, max(0, season_points))


def _normalize_preset_name(raw: str) -> str:
    return " ".join(str(raw or "").strip().split())[:24]


def _wb_week_rows(world_data: MutableMapping[str, Any], guild_id: int, week: str) -> List[Tuple[str, int, int]]:
    state = _guild_state(world_data, guild_id)
    raw = state["worldboss_weekly"].get(week, {})
    rows: List[Tuple[str, int, int]] = []
    if isinstance(raw, dict):
        for uid, row in raw.items():
            if not isinstance(row, Mapping):
                continue
            damage = _safe_int(row.get("damage"), 0, 0)
            attacks = _safe_int(row.get("attacks"), 0, 0)
            if attacks > 0 or damage > 0:
                rows.append((str(uid), damage, attacks))
    return sorted(rows, key=lambda item: (-item[1], -item[2], item[0]))


def _seed_worldboss_fallback(world_data: MutableMapping[str, Any], guild_id: int, week: str) -> None:
    """7.1 배포 직후 빈 주간 집계는 기존 v7.0 전투 데이터로 한 번 보완합니다."""
    state = _guild_state(world_data, guild_id)
    target = state["worldboss_weekly"].get(week)
    if not isinstance(target, dict):
        target = {}
        state["worldboss_weekly"][week] = target
    if target:
        return
    v630 = world_data.get("world_boss_v630", {})
    guild = v630.get("guilds", {}).get(str(guild_id), {}) if isinstance(v630, Mapping) else {}
    battles: List[Mapping[str, Any]] = []
    if isinstance(guild, Mapping):
        active = guild.get("active")
        if isinstance(active, Mapping):
            battles.append(active)
        completed = guild.get("completed", [])
        if isinstance(completed, list):
            battles.extend(item for item in completed if isinstance(item, Mapping))
    for battle in battles:
        raw_time = battle.get("defeated_at") or battle.get("spawned_at")
        point = _parse_iso(raw_time)
        if point is None or _week_key(point) != week or battle.get("test"):
            continue
        participants = battle.get("participants", {})
        if not isinstance(participants, Mapping):
            continue
        for uid, row in participants.items():
            if not isinstance(row, Mapping):
                continue
            entry = target.setdefault(str(uid), {"damage": 0, "attacks": 0})
            entry["damage"] = _safe_int(entry.get("damage")) + _safe_int(row.get("damage"), 0, 0)
            entry["attacks"] = _safe_int(entry.get("attacks")) + _safe_int(row.get("attacks"), 0, 0)


def update_command_guide(guide: List[Dict[str, Any]]) -> None:
    guide[:] = [row for row in guide if row.get("id") != GROWTH_GUIDE["id"]]
    guide.insert(0, dict(GROWTH_GUIDE))


def register_v710_growth_loop(
    bot: commands.Bot,
    get_user: Callable[[int], MutableMapping[str, Any]],
    check_registered: Callable[[commands.Context], Any],
    save_data: Callable[[], None],
    world_data: MutableMapping[str, Any],
    user_data: Mapping[str, MutableMapping[str, Any]],
    guide: List[Dict[str, Any]],
    add_title: Callable[[MutableMapping[str, Any], str], None],
    add_season_points: Callable[[MutableMapping[str, Any], int], None],
) -> None:
    if getattr(bot, "_abaddon_v710_registered", False):
        return
    bot._abaddon_v710_registered = True
    bot.abaddon_version = VERSION
    _root(world_data)
    update_command_guide(guide)

    def record_worldboss_damage(guild_id: int, user_id: int | str, damage: int) -> None:
        week = _week_key()
        # 배포 시점 이전의 같은 주 공격을 먼저 기존 v7.0 전투에서 가져온 뒤 새 피해를 더합니다.
        _seed_worldboss_fallback(world_data, int(guild_id), week)
        guild = _guild_state(world_data, int(guild_id))
        board = guild["worldboss_weekly"].get(week)
        if not isinstance(board, dict):
            board = {}
            guild["worldboss_weekly"][week] = board
        row = board.setdefault(str(user_id), {"damage": 0, "attacks": 0})
        if not isinstance(row, dict):
            row = {"damage": 0, "attacks": 0}
            board[str(user_id)] = row
        row["damage"] = _safe_int(row.get("damage")) + max(0, _safe_int(damage))
        row["attacks"] = _safe_int(row.get("attacks")) + 1
        user = get_user(int(user_id))
        state = _user_state(user)
        daily = state["daily"]
        weekly = state["weekly"]
        daily["counters"]["worldboss"] = _safe_int(daily["counters"].get("worldboss")) + 1
        weekly["counters"]["worldboss"] = _safe_int(weekly["counters"].get("worldboss")) + 1
        daily["counters"]["combat"] = _safe_int(daily["counters"].get("combat")) + 1
        weekly["counters"]["combat"] = _safe_int(weekly["counters"].get("combat")) + 1
        daily["counted_actions"] = min(MAX_DAILY_COUNTED_ACTIONS, _safe_int(daily.get("counted_actions")) + 1)
        state["lifetime"]["participation"] = _safe_int(state["lifetime"].get("participation")) + 1
        _touch_seen(state)
        _sync_daily_clear(user)

    bot.v710_record_worldboss_damage = record_worldboss_damage

    @bot.listen("on_command")
    async def growth_activity_before(ctx: commands.Context) -> None:
        command = getattr(ctx, "command", None)
        name = str(getattr(command, "name", "") or "")
        category = _find_category(name)
        if not category:
            return
        try:
            user = get_user(ctx.author.id)
            ctx._v710_activity_category = category
            ctx._v710_activity_fingerprint = _activity_fingerprint(user, category)
        except Exception:
            return

    @bot.listen("on_command_completion")
    async def growth_activity_listener(ctx: commands.Context) -> None:
        command = getattr(ctx, "command", None)
        name = str(getattr(command, "name", "") or "")
        category = getattr(ctx, "_v710_activity_category", None) or _find_category(name)
        if not category:
            return
        try:
            user = get_user(ctx.author.id)
            if not isinstance(user, MutableMapping):
                return
            before = getattr(ctx, "_v710_activity_fingerprint", None)
            after = _activity_fingerprint(user, category)
            # 운세·퀴즈·브리핑 같은 확인형 명령은 성공 종료 자체를 활동으로 인정합니다.
            if category != "signal" and before == after:
                return
            changed = _record_activity(user, category, name)
            cleared = _sync_daily_clear(user)
            if changed or cleared:
                save_data()
        except Exception as exc:
            print(f"[V7.1 성장 집계 경고] {type(exc).__name__}: {exc}", flush=True)

    async def growth_board_embed(ctx: commands.Context, user: MutableMapping[str, Any]) -> discord.Embed:
        cleared_now = _sync_daily_clear(user)
        state = _user_state(user)
        flags, daily_done = _daily_status(user)
        weekly_flags, weekly_done = _weekly_status(user)
        life = state["lifetime"]
        title = "🌱 성장 루프 작전 보드"
        description = (
            f"{ctx.author.mention} · 오늘 **{daily_done}/6** · 이번 주 **{weekly_done}/6**\n"
            f"🔥 연속 완주 **{_safe_int(life.get('streak'))}일** · 🏅 참여 점수 **{_safe_int(life.get('participation'))}** · ✦ 성장 인장 **{_safe_int(life.get('growth_marks'))}개**"
        )
        if cleared_now:
            description += "\n\n🎉 **오늘의 성장 루프를 완주했습니다!** `!미션보상`으로 보상을 받으세요."
        embed = discord.Embed(title=title, description=description, color=0x63C174)
        embed.add_field(name="☀️ 일일 미션 · 6개 중 5개 완주", value="\n".join(_daily_lines(user)), inline=False)
        embed.add_field(name=f"📆 주간 미션 · {state['weekly']['week']}", value="\n".join(_weekly_lines(user)), inline=False)
        next_label, next_command = _next_action(user)
        reward_state = "✅ 수령 완료" if state["daily"].get("reward_claimed") else "🎁 수령 가능" if state["daily"].get("completed") else "🔒 진행 중"
        embed.add_field(name="🧭 다음 추천", value=f"**{next_label}** · `{next_command}`", inline=True)
        embed.add_field(name="🎁 오늘 보상", value=reward_state, inline=True)
        embed.set_footer(text="사진 없이 이모지 진행률로 표시 · 보상: !미션보상 · 프리셋: !장비프리셋")
        if cleared_now:
            save_data()
        return embed

    async def today_callback(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        embed = await growth_board_embed(ctx, user)
        embed.title = f"📋 {ctx.author.display_name}님의 오늘 할 일"
        await ctx.send(embed=embed)

    existing_today = bot.get_command("오늘할일")
    if existing_today is not None:
        existing_today.callback = today_callback

    @bot.command(name="성장보드", aliases=["미션보드", "성장루프", "작전보드"])
    async def growth_board(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        await ctx.send(embed=await growth_board_embed(ctx, user))

    @bot.command(name="미션보상", aliases=["성장보상", "루프보상"])
    async def mission_reward(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        _sync_daily_clear(user)
        state = _user_state(user)
        rewards: List[str] = []
        if state["daily"].get("completed") and not state["daily"].get("reward_claimed"):
            streak = _safe_int(state["lifetime"].get("streak"))
            streak_bonus = min(5_000, streak * 500)
            _apply_reward(user, 7_500 + streak_bonus, 1, 20, add_season_points)
            state["daily"]["reward_claimed"] = True
            rewards.append(f"☀️ 일일 완주: 식량 **{7_500 + streak_bonus:,}** · 시즌 **20P** · 성장 인장 **1개**")
        _, weekly_done = _weekly_status(user)
        claimed = state["weekly"].setdefault("claimed_tiers", [])
        for need, food, season, title in WEEKLY_TIERS:
            if weekly_done < need or need in claimed:
                continue
            marks = max(1, need // 2)
            _apply_reward(user, food, marks, season, add_season_points)
            claimed.append(need)
            if title:
                add_title(user, title)
            rewards.append(f"📆 주간 {need}/6 단계: 식량 **{food:,}** · 시즌 **{season}P** · 성장 인장 **{marks}개**" + (f" · 칭호 `{title}`" if title else ""))
        if not rewards:
            await ctx.send("🔒 현재 수령 가능한 미션 보상이 없습니다. `!성장보드`에서 진행률을 확인하세요.")
            return
        save_data()
        embed = discord.Embed(title="🎁 성장 루프 보상 정산", description="\n".join(f"✨ {row}" for row in rewards), color=discord.Color.gold())
        embed.add_field(name="현재 보유", value=f"🥫 **{_safe_int(user.get('balance')):,} 식량** · ✦ **{_safe_int(state['lifetime'].get('growth_marks'))} 성장 인장**", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="누적보상", aliases=["참여보상", "성장이정표"])
    async def lifetime_reward(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        state = _user_state(user)
        life = state["lifetime"]
        participation = _safe_int(life.get("participation"))
        claimed = life.setdefault("claimed_milestones", [])
        rewards: List[str] = []
        for target, food, marks, title in LIFETIME_MILESTONES:
            if participation < target or target in claimed:
                continue
            _apply_reward(user, food, marks, target // 2, add_season_points)
            claimed.append(target)
            if title:
                add_title(user, title)
            rewards.append(f"🏅 **{target}점 이정표** · 식량 {food:,} · 인장 {marks}개" + (f" · `{title}`" if title else ""))
        if rewards:
            save_data()
            await ctx.send(embed=discord.Embed(title="🎊 누적 참여 보상", description="\n".join(rewards), color=0xC99B3E))
            return
        next_row = next((row for row in LIFETIME_MILESTONES if row[0] not in claimed and row[0] > participation), None)
        if next_row:
            await ctx.send(f"🏅 현재 참여 점수 **{participation}점**\n{_bar(participation, next_row[0])} 다음 보상까지 **{next_row[0] - participation}점**")
        else:
            await ctx.send(f"🏆 누적 참여 보상을 모두 수령했습니다. 현재 **{participation}점**")

    @bot.command(name="장비프리셋", aliases=["레이드프리셋", "프리셋"])
    async def equipment_preset(ctx: commands.Context, 동작: str = "목록", *, 이름: str = "") -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        state = _user_state(user)
        presets = state["presets"]
        action = str(동작 or "목록").strip().lower()
        name = _normalize_preset_name(이름)
        if action in {"목록", "list", "확인"}:
            lines = []
            for preset_name, row in presets.items():
                equipment = row.get("equipment", {}) if isinstance(row, Mapping) else {}
                count = sum(1 for value in equipment.values() if value) if isinstance(equipment, Mapping) else 0
                lines.append(f"🎒 **{preset_name}** · 장비 {count}개 · `{row.get('saved_at', '-')[:10]}`")
            usage = "`!장비프리셋 저장 레이드` · `!장비프리셋 적용 레이드` · `!장비프리셋 삭제 레이드`"
            await ctx.send(embed=discord.Embed(title=f"🎒 장비 프리셋 {len(presets)}/{MAX_PRESETS}", description=("\n".join(lines) or "저장된 프리셋이 없습니다.") + f"\n\n{usage}", color=0x4E79A7))
            return
        if action in {"저장", "save"}:
            if not name:
                await ctx.send("⚠️ 프리셋 이름을 입력하세요. 예: `!장비프리셋 저장 레이드`")
                return
            if name not in presets and len(presets) >= MAX_PRESETS:
                await ctx.send(f"⚠️ 프리셋은 최대 **{MAX_PRESETS}개**까지 저장할 수 있습니다.")
                return
            equipment = user.get("equipment", {})
            if not isinstance(equipment, Mapping) or not any(equipment.values()):
                await ctx.send("⚠️ 현재 장착 중인 장비가 없습니다.")
                return
            presets[name] = {"equipment": dict(equipment), "saved_at": _now().isoformat()}
            save_data()
            await ctx.send(f"💾 **{name}** 프리셋 저장 완료!\n" + " ".join("✅" if item else "▫️" for item in equipment.values()))
            return
        if action in {"적용", "load", "사용"}:
            row = presets.get(name)
            if not name or not isinstance(row, Mapping):
                await ctx.send("⚠️ 저장된 프리셋 이름을 찾지 못했습니다. `!장비프리셋`으로 목록을 확인하세요.")
                return
            equipment = row.get("equipment", {})
            inventory = set(str(item) for item in user.get("inventory", []) if item)
            current = user.get("equipment", {})
            if not isinstance(current, dict) or not isinstance(equipment, Mapping):
                await ctx.send("⚠️ 장비 데이터 형식이 올바르지 않습니다.")
                return
            owned = inventory | {str(item) for item in current.values() if item}
            applied = 0
            missing: List[str] = []
            for slot, item in equipment.items():
                if item and str(item) not in owned:
                    missing.append(str(item))
                    continue
                current[str(slot)] = item
                if item:
                    applied += 1
            save_data()
            text = f"⚡ **{name}** 프리셋 적용 · 장비 **{applied}개**\n🧬 세트 효과 확인: `!세트효과`"
            if missing:
                text += "\n⚠️ 미보유 장비 제외: " + ", ".join(missing[:6])
            await ctx.send(text)
            return
        if action in {"삭제", "delete", "제거"}:
            if name not in presets:
                await ctx.send("⚠️ 삭제할 프리셋을 찾지 못했습니다.")
                return
            del presets[name]
            save_data()
            await ctx.send(f"🗑️ **{name}** 프리셋을 삭제했습니다.")
            return
        await ctx.send("⚠️ 동작은 `목록`, `저장`, `적용`, `삭제` 중 하나입니다.")

    @bot.command(name="월드보스주간랭킹", aliases=["월보주간랭킹", "주간월보랭킹"])
    async def worldboss_weekly_ranking(ctx: commands.Context, 기간: str = "이번주") -> None:
        if not await check_registered(ctx):
            return
        if ctx.guild is None:
            await ctx.send("⚠️ 서버 채널에서만 확인할 수 있습니다.")
            return
        token = str(기간 or "이번주").replace(" ", "")
        week = _previous_week_key() if token in {"지난주", "저번주", "previous"} else _week_key()
        _seed_worldboss_fallback(world_data, ctx.guild.id, week)
        rows = _wb_week_rows(world_data, ctx.guild.id, week)
        if not rows:
            await ctx.send(f"📭 `{week}` 월드보스 주간 기록이 없습니다.")
            return
        total = sum(row[1] for row in rows)
        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for index, (uid, damage, attacks) in enumerate(rows[:15], 1):
            icon = medals[index - 1] if index <= 3 else "▫️"
            share = damage / max(1, total) * 100
            lines.append(f"{icon} **{index}위** <@{uid}> · `{damage:,}` 피해 · {attacks}회 · {share:.1f}%")
        embed = discord.Embed(title=f"🏆 월드보스 주간 랭킹 · {week}", description="\n".join(lines), color=discord.Color.gold())
        embed.set_footer(text="지난주 보상: !월드보스주간보상 · 7.1 이후 공격은 주차별로 정확히 집계")
        await ctx.send(embed=embed)

    @bot.command(name="월드보스주간보상", aliases=["월보주간보상"])
    async def worldboss_weekly_reward(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        if ctx.guild is None:
            await ctx.send("⚠️ 서버 채널에서만 받을 수 있습니다.")
            return
        user = get_user(ctx.author.id)
        week = _previous_week_key()
        _seed_worldboss_fallback(world_data, ctx.guild.id, week)
        rows = _wb_week_rows(world_data, ctx.guild.id, week)
        uid = str(ctx.author.id)
        rank = next((index for index, row in enumerate(rows, 1) if row[0] == uid), None)
        if rank is None:
            await ctx.send(f"📭 `{week}` 월드보스 참가 기록이 없습니다.")
            return
        guild = _guild_state(world_data, ctx.guild.id)
        claimed = guild["worldboss_claimed"].get(week)
        if not isinstance(claimed, list):
            claimed = []
            guild["worldboss_claimed"][week] = claimed
        if uid in claimed:
            await ctx.send("⚠️ 지난주 월드보스 랭킹 보상을 이미 받았습니다.")
            return
        if rank == 1:
            food, season, marks, title = 60_000, 120, 6, "주간 월드보스 최우수 토벌자"
        elif rank <= 3:
            food, season, marks, title = 42_000, 90, 4, "주간 월드보스 선봉대"
        elif rank <= 10:
            food, season, marks, title = 25_000, 60, 3, None
        else:
            food, season, marks, title = 12_000, 30, 1, None
        _apply_reward(user, food, marks, season, add_season_points)
        if title:
            add_title(user, title)
        claimed.append(uid)
        save_data()
        damage = rows[rank - 1][1]
        embed = discord.Embed(title="🌋 지난주 월드보스 보상", description=f"`{week}` · **{rank}위** · 누적 피해 **{damage:,}**", color=0xD35400)
        embed.add_field(name="보상", value=f"🥫 식량 **{food:,}**\n🎖️ 시즌 **{season}P**\n✦ 성장 인장 **{marks}개**" + (f"\n🏷️ `{title}`" if title else ""), inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="복귀보급", aliases=["신규보급", "따라잡기보급"])
    async def catchup_support(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        state = _user_state(user)
        support = state["support"]
        level = _safe_int(user.get("level"), 1, 1)
        is_new = level <= 3 and _safe_int(user.get("stats", {}).get("earned") if isinstance(user.get("stats"), Mapping) else 0) < 25_000
        kind = None
        if is_new and not support.get("new_claimed"):
            kind = "new"
            food, marks = 15_000, 2
        elif support.get("return_eligible") and support.get("return_claimed_period") != support.get("return_period"):
            kind = "return"
            food, marks = 30_000, 3
        if kind is None:
            await ctx.send("🧭 현재 수령 가능한 신규·복귀 보급이 없습니다. 복귀 보급은 향후 **14일 이상 미접속** 기록부터 자동 판정됩니다.")
            _touch_seen(state)
            save_data()
            return
        _apply_reward(user, food, marks, 30 if kind == "new" else 60, add_season_points)
        materials = user.setdefault("materials", {})
        if isinstance(materials, dict):
            materials["수리 키트"] = _safe_int(materials.get("수리 키트")) + 2
            materials["강화보호권"] = _safe_int(materials.get("강화보호권")) + 1
        if kind == "new":
            support["new_claimed"] = True
            label = "🌱 신규 생존자 보급"
        else:
            support["return_claimed_period"] = support.get("return_period")
            support["return_eligible"] = False
            label = "🔥 복귀 생존자 보급"
        _touch_seen(state)
        save_data()
        await ctx.send(f"{label} 지급 완료!\n🥫 식량 **{food:,}** · ✦ 성장 인장 **{marks}개** · 🧰 수리 키트 **2개** · 🛡️ 강화보호권 **1개**")

    # 기존 단일 퀘스트 화면도 이미지 없이 이모지 진행률을 강화합니다.
    async def daily_quest_callback(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        quest = user.get("daily_quest", {})
        current = _safe_int(quest.get("progress"))
        target = _safe_int(quest.get("target"), 1, 1)
        status = "✅ 완료" if current >= target else "🟨 진행 중"
        claimed = "🎁 수령 완료" if quest.get("claimed") else "🎁 보상 대기" if current >= target else "🔒 미완료"
        embed = discord.Embed(title="🎯 오늘의 기존 퀘스트", description=f"**{quest.get('type', '임무 준비 중')} {target}회**", color=0xE6A23C)
        embed.add_field(name="진행", value=f"{_bar(current, target)}\n**{current}/{target}** · {status}", inline=False)
        embed.add_field(name="보상", value=f"🥫 **{_safe_int(quest.get('reward')):,} 식량** · {claimed}", inline=False)
        embed.set_footer(text="통합 성장 루프: !성장보드 · 기존 퀘스트 보상: !퀘스트보상")
        await ctx.send(embed=embed)

    async def weekly_quest_callback(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        # get_user가 기존 주간 퀘스트를 보장하지만 구버전 데이터도 안전하게 처리합니다.
        quest = user.get("weekly_quest", {})
        current = _safe_int(quest.get("progress"))
        target = _safe_int(quest.get("target"), 1, 1)
        embed = discord.Embed(title=f"📆 기존 주간 퀘스트 · {quest.get('week', _week_key())}", description=f"**{quest.get('type', '주간 임무')} {target}회**", color=0x5B8FF9)
        embed.add_field(name="진행", value=f"{_bar(current, target)}\n**{current}/{target}** · {'✅ 완료' if current >= target else '🟨 진행 중'}", inline=False)
        embed.add_field(name="보상", value=f"🥫 **{_safe_int(quest.get('reward')):,} 식량** · {'✅ 수령 완료' if quest.get('claimed') else '🎁 수령 가능' if current >= target else '🔒 미완료'}", inline=False)
        embed.set_footer(text="통합 주간 미션: !성장보드 · 기존 주간 보상: !주간보상")
        await ctx.send(embed=embed)

    for command_name, callback in (("일일퀘스트", daily_quest_callback), ("주간퀘스트", weekly_quest_callback)):
        command = bot.get_command(command_name)
        if command is not None:
            command.callback = callback
