import discord
from discord.ext import commands, tasks
from apocalypse_bot.core import rate_limit_guard as discord_rate_guard
import random
import asyncio
import json
import os
import traceback
import shutil
import threading
import difflib
import uuid
import time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from apocalypse_bot.game_data.jobs import JOBS
from apocalypse_bot.commands.conditions import (
    apply_dungeon_conditions, condition_text, ensure_conditions,
    exploration_modifier, refresh_conditions, register_condition_commands,
)
from apocalypse_bot.commands.v635_visuals import (
    apply_base_reaction_visual, apply_base_stage_visual, format_remaining, parse_iso,
)
from apocalypse_bot.commands.v636_world_combat import (
    weather_combat_multiplier, weather_life_modifiers,
)
from apocalypse_bot.commands.v637_dynamic_events import (
    active_fortune_modifiers, consume_weapon_durability,
    equipment_condition_multiplier, equipment_mod_power_bonus,
    equipment_mod_stat_bonus, weapon_durability_status,
)
from apocalypse_bot.commands.status import (
    DUNGEON_STAMINA_COSTS, LIFE_STAMINA_COSTS, apply_damage,
    ensure_vitals, get_max_hp, get_max_stamina, refresh_vitals,
    register_status_commands, spend_stamina,
)

# =========================================================
# 기본 설정
# =========================================================
load_dotenv()

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# V13.3.0: install before every extension so a duplicate alias cannot abort boot.
from apocalypse_bot.commands.v1330_command_registry_guard import install_command_registry_guard
install_command_registry_guard(bot)

DATA_FILE = os.getenv("DATA_FILE", "/var/data/survival_data.json")
DATA_BACKUP_DIR = os.getenv("DATA_BACKUP_DIR", os.path.join(os.path.dirname(DATA_FILE) or ".", "backups"))
BACKUP_RETENTION = max(5, int(os.getenv("BACKUP_RETENTION", "30") or 30))
AUTO_BACKUP_EVERY_SAVES = max(10, int(os.getenv("AUTO_BACKUP_EVERY_SAVES", "50") or 50))
CORRECT_PASSWORD = "생존자"
MAX_MESSAGE_LENGTH = 1900
KST = timezone(timedelta(hours=9))
_LOAD_RECOVERY_STATUS = {"source": "new", "recovered": False, "error": "", "loaded_at": ""}

# =========================================================
# 데이터 로드 / 저장 / 마이그레이션
# =========================================================
def _safe_backup_reason(value):
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(value or "auto"))
    return cleaned[:32] or "auto"


def validate_data_snapshot(path):
    """JSON 데이터 스냅샷을 읽어 구조와 기본 통계를 반환합니다."""
    result = {
        "path": str(path), "exists": False, "valid": False, "size": 0,
        "users": 0, "world_keys": 0, "modified_at": "", "error": "",
    }
    try:
        if not os.path.isfile(path):
            result["error"] = "파일 없음"
            return result
        stat = os.stat(path)
        result["exists"] = True
        result["size"] = stat.st_size
        result["modified_at"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError("루트가 객체가 아닙니다.")
        if "users" not in payload:
            legacy_users = {k: v for k, v in payload.items() if str(k).isdigit() and isinstance(v, dict)}
            payload = {"users": legacy_users, "world": {}}
        users = payload.get("users")
        world = payload.get("world")
        if not isinstance(users, dict) or not isinstance(world, dict):
            raise ValueError("users/world 구조가 올바르지 않습니다.")
        result.update(valid=True, users=len(users), world_keys=len(world))
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"[:300]
    return result


def list_data_backups():
    try:
        os.makedirs(DATA_BACKUP_DIR, exist_ok=True)
    except OSError:
        return []
    rows = []
    for name in os.listdir(DATA_BACKUP_DIR):
        if not name.endswith(".json"):
            continue
        path = os.path.join(DATA_BACKUP_DIR, name)
        if not os.path.isfile(path):
            continue
        state = validate_data_snapshot(path)
        state["name"] = name
        rows.append(state)
    rows.sort(key=lambda row: row.get("modified_at", ""), reverse=True)
    return rows


def create_data_backup(reason="manual"):
    """현재 주 데이터를 검증한 뒤 타임스탬프 백업으로 보존합니다."""
    current = validate_data_snapshot(DATA_FILE)
    if not current.get("valid"):
        raise ValueError(f"주 데이터 검증 실패: {current.get('error') or '알 수 없음'}")
    os.makedirs(DATA_BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"survival_data_{stamp}_{_safe_backup_reason(reason)}.json"
    target = os.path.join(DATA_BACKUP_DIR, filename)
    temp = f"{target}.tmp"
    try:
        shutil.copy2(DATA_FILE, temp)
        checked = validate_data_snapshot(temp)
        if not checked.get("valid"):
            raise ValueError(f"백업 검증 실패: {checked.get('error')}")
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            try:
                os.remove(temp)
            except OSError:
                pass
    rows = list_data_backups()
    for old in rows[BACKUP_RETENTION:]:
        try:
            os.remove(old["path"])
        except OSError:
            pass
    result = validate_data_snapshot(target)
    result["name"] = filename
    result["reason"] = str(reason)
    return result


def load_data():
    """주 데이터가 손상되면 .bak 및 최근 정상 스냅샷까지 순서대로 복구합니다."""
    global _LOAD_RECOVERY_STATUS
    backups = [row["path"] for row in list_data_backups() if row.get("valid")]
    candidates = [DATA_FILE, f"{DATA_FILE}.bak", *backups]
    raw = None
    loaded_from = ""
    errors = []
    seen = set()
    for candidate in candidates:
        if candidate in seen or not os.path.exists(candidate):
            continue
        seen.add(candidate)
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                value = json.load(f)
            if isinstance(value, dict):
                raw = value
                loaded_from = candidate
                break
            errors.append(f"{candidate}: 루트 형식 오류")
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            line = f"{candidate}: {type(exc).__name__}: {exc}"
            errors.append(line)
            print(f"[데이터 로드 경고] {line}", flush=True)

    _LOAD_RECOVERY_STATUS = {
        "source": loaded_from or "new",
        "recovered": bool(loaded_from and loaded_from != DATA_FILE),
        "error": " | ".join(errors[-3:])[:600],
        "loaded_at": datetime.now().isoformat(),
    }
    if raw is None:
        try:
            from apocalypse_bot.core.storage_sqlite import load_snapshot
            db_snapshot = load_snapshot()
        except Exception as db_exc:
            db_snapshot = None
            errors.append(f"sqlite: {type(db_exc).__name__}: {db_exc}")
        if isinstance(db_snapshot, dict) and isinstance(db_snapshot.get("users"), dict) and isinstance(db_snapshot.get("world"), dict):
            _LOAD_RECOVERY_STATUS = {
                "source": "sqlite",
                "recovered": True,
                "error": " | ".join(errors[-3:])[:600],
                "loaded_at": datetime.now().isoformat(),
            }
            print("[데이터 자동 복구] SQLite 미러에서 정상 스냅샷을 불러왔습니다.", flush=True)
            return db_snapshot
        return {"users": {}, "world": {}}
    if loaded_from != DATA_FILE:
        print(f"[데이터 자동 복구] 정상 스냅샷을 불러왔습니다: {loaded_from}", flush=True)

    if "users" not in raw:
        old_users = {k: v for k, v in raw.items() if str(k).isdigit() and isinstance(v, dict)}
        return {"users": old_users, "world": {}}

    raw.setdefault("users", {})
    raw.setdefault("world", {})
    return raw


data = load_data()
user_data = data["users"]
world_data = data["world"]

# v18.1 Phase-1 DB migration: immediately create/update the SQLite safety mirror
# without changing the legacy JSON source of truth. A DB failure never blocks startup.
try:
    from apocalypse_bot.core.storage_sqlite import mirror_snapshot as _initial_sqlite_mirror
    _initial_sqlite_mirror(user_data, world_data, source_json=DATA_FILE)
except Exception as _initial_sqlite_exc:
    print(f"[SQLite 초기 미러 경고] {type(_initial_sqlite_exc).__name__}: {_initial_sqlite_exc}", flush=True)


_SAVE_LOCK = threading.Lock()
_SAVE_COUNT = 0
_LAST_SAVE_AT = ""
_LAST_BACKUP_AT = ""
_LAST_SAVE_ERROR = ""


def save_data():
    """원자적 저장 + 쓰기 검증 + 최근 정상본 백업.

    단일 이벤트 루프에서도 여러 명령이 연달아 저장할 수 있으므로 임시 파일을
    완전히 기록·검증한 뒤 교체합니다. 기존 정상 파일은 .bak으로 한 단계 보존합니다.
    """
    global _SAVE_COUNT, _LAST_SAVE_AT, _LAST_BACKUP_AT, _LAST_SAVE_ERROR
    directory = os.path.dirname(DATA_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)

    payload = {"users": user_data, "world": world_data}
    temp_file = f"{DATA_FILE}.tmp"
    backup_file = f"{DATA_FILE}.bak"
    with _SAVE_LOCK:
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=4)
                f.flush()
                os.fsync(f.fileno())
            # 교체 전에 JSON을 다시 읽어 잘린 파일이나 직렬화 오류를 차단합니다.
            with open(temp_file, "r", encoding="utf-8") as verify:
                checked = json.load(verify)
            if not isinstance(checked, dict) or "users" not in checked or "world" not in checked:
                raise ValueError("저장 검증 실패: users/world 루트가 없습니다.")
            if os.path.isfile(DATA_FILE):
                try:
                    shutil.copy2(DATA_FILE, backup_file)
                except OSError as backup_exc:
                    print(f"[데이터 백업 경고] {type(backup_exc).__name__}: {backup_exc}", flush=True)
            os.replace(temp_file, DATA_FILE)
            try:
                from apocalypse_bot.core.storage_sqlite import mirror_snapshot
                mirror_snapshot(user_data, world_data, source_json=DATA_FILE)
            except Exception as sqlite_exc:
                # JSON remains the compatibility source of truth; a mirror failure must never block gameplay saves.
                print(f"[SQLite 미러 경고] {type(sqlite_exc).__name__}: {sqlite_exc}", flush=True)
            _SAVE_COUNT += 1
            _LAST_SAVE_AT = datetime.now().isoformat()
            _LAST_SAVE_ERROR = ""
            if _SAVE_COUNT % AUTO_BACKUP_EVERY_SAVES == 0:
                try:
                    snapshot = create_data_backup("auto")
                    _LAST_BACKUP_AT = snapshot.get("modified_at", _LAST_SAVE_AT)
                except Exception as backup_exc:
                    print(f"[자동 스냅샷 경고] {type(backup_exc).__name__}: {backup_exc}", flush=True)
        except Exception as save_exc:
            _LAST_SAVE_ERROR = f"{type(save_exc).__name__}: {save_exc}"[:500]
            raise
        finally:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError:
                    pass


def default_user():
    return {
        "balance": 1000,
        "registration": {
            "registered_at": "",
            "guild_id": "",
            "guild_name": "",
            "source": "legacy",
        },
        "level": 1,
        "exp": 0,
        "job": None,
        "job_changed_at": "",
        "hp": 100,
        "stamina": 100,
        "last_vitals_update": "",
        "infection": 0,
        "conditions": {"출혈": 0, "감염": 0, "중독": 0, "골절": 0, "기절": 0},
        "medical_items": {"붕대": 0, "소독약": 0, "항생제": 0, "진통제": 0, "백신": 0},
        "last_condition_update": "",
        "last_attendance": "",
        "inventory": [],
        "equipment": {"무기": None, "방어구": None, "머리": None, "장갑": None, "신발": None, "반지": None, "목걸이": None},
        "identified_items": [],
        "enhancements": {},
        "equipment_durability": {},
        "weapon_mods": {},
        "equipment_options": {},
        "dungeon_v21": {"max_floor": 1, "best_floor": 0, "clears": 0, "hidden_kills": 0},
        "life_mastery": {"채집": 0, "낚시": 0, "벌목": 0, "광산": 0},
        "worldboss_codex": {},
        "collection_codex": {"items": [], "pets": [], "monsters": {}, "claimed_milestones": []},
        "dungeon_monster_kills": {},
        "tutorial": {"started": False, "step": 0, "completed": False, "skipped": False, "rewards_received": 0},
        "story": {"version": 1, "started": False, "completed": False, "node": "s1_signal", "flags": [], "history": [], "ending": None, "endings": [], "claimed_rewards": [], "runs": 0},
        "market_history": [],
        "pet": None,
        "pet_level": 1,
        "pet_collection": {},
        "materials": {},
        "title": "신입 생존자",
        "titles": ["신입 생존자"],
        "achievements": [],
        "stats": {
            "dungeon_wins": 0,
            "dungeon_losses": 0,
            "boss_damage": 0,
            "worldboss_damage": 0,
            "items_bought": 0,
            "craft_count": 0,
            "enhance_success": 0,
            "gambles": 0,
            "earned": 0,
            "random_boxes": 0
        },
        "daily_quest": {
            "date": "",
            "type": "",
            "target": 0,
            "progress": 0,
            "reward": 0,
            "claimed": False
        },
        "weekly_quest": {
            "week": "",
            "type": "",
            "target": 0,
            "progress": 0,
            "reward": 0,
            "claimed": False
        },
        "attendance_streak": 0,
        "attendance_milestones": [],
        "daily_quiz": {"date": "", "solved": False, "attempts": 0, "correct": 0, "total_correct": 0},
        "base": {
            "level": 1,
            "last_collect": "",
            "storage": 0,
            "built": False,
            "upgrade_target": 0,
            "upgrade_started_at": "",
            "upgrade_complete_at": ""
        },
        "resources": {
            "나무": 0,
            "광석": 0,
            "물고기": 0,
            "약초": 0,
            "고철": 0
        },
        "guild_id": None,
        "region": "폐허도심",
        "region_discoveries": ["폐허도심"],
        "zombie_kills": {},
        "exploration_count": 0,
        "season_pass": {
            "season": "",
            "points": 0,
            "claimed_levels": []
        },
        "black_casino": {},
        "finance": {},
        "daily_fortune": {},
        "radio_event": {},
        "crow_purchases": {},
        "random_box_daily": {}
    }



def _safe_int(value, default=0, minimum=None):
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = int(default)
    if minimum is not None:
        result = max(minimum, result)
    return result


def ensure_dungeon_user_state(u):
    """구버전 가입 데이터도 던전 보상 처리에서 안전하게 사용할 수 있게 정리합니다."""
    if not isinstance(u, dict):
        return u

    u["balance"] = _safe_int(u.get("balance", 1000), 1000)
    u["level"] = _safe_int(u.get("level", 1), 1, 1)
    u["exp"] = _safe_int(u.get("exp", 0), 0, 0)
    u["infection"] = _safe_int(u.get("infection", 0), 0, 0)

    stats = u.get("stats")
    if not isinstance(stats, dict):
        stats = {}
        u["stats"] = stats
    for key in [
        "dungeon_wins", "dungeon_losses", "boss_damage", "worldboss_damage",
        "items_bought", "craft_count", "enhance_success", "gambles", "earned",
    ]:
        stats[key] = _safe_int(stats.get(key, 0), 0, 0)

    for key in ["materials", "enhancements", "equipment_durability", "weapon_mods", "daily_fortune", "radio_event", "crow_purchases", "random_box_daily", "dungeon_monster_kills"]:
        if not isinstance(u.get(key), dict):
            u[key] = {}

    inventory = u.get("inventory")
    if not isinstance(inventory, list):
        if isinstance(inventory, (tuple, set)):
            u["inventory"] = list(inventory)
        elif isinstance(inventory, dict):
            u["inventory"] = list(inventory.keys())
        else:
            u["inventory"] = []

    achievements = u.get("achievements")
    if not isinstance(achievements, list):
        if isinstance(achievements, dict):
            u["achievements"] = list(achievements.keys())
        elif isinstance(achievements, (tuple, set)):
            u["achievements"] = list(achievements)
        elif achievements:
            u["achievements"] = [str(achievements)]
        else:
            u["achievements"] = []

    titles = u.get("titles")
    if not isinstance(titles, list):
        u["titles"] = [str(u.get("title") or "신입 생존자")]

    return u


def migrate_user(u):
    base = default_user()

    for key, value in base.items():
        if key not in u:
            if isinstance(value, dict):
                u[key] = value.copy()
            elif isinstance(value, list):
                u[key] = value.copy()
            else:
                u[key] = value

    if not isinstance(u.get("stats"), dict):
        u["stats"] = {}
    if not isinstance(u.get("daily_quest"), dict):
        u["daily_quest"] = base["daily_quest"].copy()

    for key, value in base["stats"].items():
        u["stats"].setdefault(key, value)

    for key, value in base["daily_quest"].items():
        u["daily_quest"].setdefault(key, value)

    for nested_key in ["weekly_quest", "base", "resources", "season_pass"]:
        if not isinstance(u.get(nested_key), dict):
            u[nested_key] = base[nested_key].copy()
        for key, value in base[nested_key].items():
            if isinstance(value, list):
                u[nested_key].setdefault(key, value.copy())
            else:
                u[nested_key].setdefault(key, value)

    if not isinstance(u.get("equipment"), dict):
        u["equipment"] = base["equipment"].copy()
    for slot, value in base["equipment"].items():
        u["equipment"].setdefault(slot, value)
    if not isinstance(u.get("identified_items"), list):
        u["identified_items"] = []
    if not isinstance(u.get("enhancements"), dict):
        u["enhancements"] = {}
    if not isinstance(u.get("equipment_durability"), dict):
        u["equipment_durability"] = {}
    if not isinstance(u.get("weapon_mods"), dict):
        u["weapon_mods"] = {}
    for dynamic_key in ["daily_fortune", "radio_event", "crow_purchases", "random_box_daily"]:
        if not isinstance(u.get(dynamic_key), dict):
            u[dynamic_key] = {}
    if not isinstance(u.get("equipment_options"), dict):
        u["equipment_options"] = {}
    if not isinstance(u.get("dungeon_v21"), dict):
        u["dungeon_v21"] = base["dungeon_v21"].copy()
    for key, value in base["dungeon_v21"].items():
        u["dungeon_v21"].setdefault(key, value)
    if not isinstance(u.get("life_mastery"), dict):
        u["life_mastery"] = base["life_mastery"].copy()
    for key, value in base["life_mastery"].items():
        u["life_mastery"].setdefault(key, value)
    if not isinstance(u.get("worldboss_codex"), dict):
        u["worldboss_codex"] = {}
    if not isinstance(u.get("collection_codex"), dict):
        u["collection_codex"] = base["collection_codex"].copy()
    for key, value in base["collection_codex"].items():
        if isinstance(value, list):
            u["collection_codex"].setdefault(key, value.copy())
        elif isinstance(value, dict):
            u["collection_codex"].setdefault(key, value.copy())
        else:
            u["collection_codex"].setdefault(key, value)
    if not isinstance(u.get("dungeon_monster_kills"), dict):
        u["dungeon_monster_kills"] = {}
    if not isinstance(u.get("tutorial"), dict):
        u["tutorial"] = base["tutorial"].copy()
    for key, value in base["tutorial"].items():
        u["tutorial"].setdefault(key, value)
    if not isinstance(u.get("story"), dict):
        u["story"] = base["story"].copy()
    for key, value in base["story"].items():
        if isinstance(value, list):
            u["story"].setdefault(key, value.copy())
        else:
            u["story"].setdefault(key, value)
    if not isinstance(u["story"].get("flags"), list):
        u["story"]["flags"] = []
    if not isinstance(u["story"].get("history"), list):
        u["story"]["history"] = []
    if not isinstance(u["story"].get("endings"), list):
        u["story"]["endings"] = []
    if not isinstance(u["story"].get("claimed_rewards"), list):
        u["story"]["claimed_rewards"] = []
    if not isinstance(u.get("market_history"), list):
        u["market_history"] = []

    # V3.5 펫 동료 시스템: 기존 단일 펫 데이터를 컬렉션 형태로 자동 이전합니다.
    if not isinstance(u.get("pet_collection"), dict):
        u["pet_collection"] = {}
    active_pet = u.get("pet")
    if active_pet:
        record = u["pet_collection"].setdefault(active_pet, {})
        record.setdefault("level", max(1, int(u.get("pet_level", 1) or 1)))
        record.setdefault("exp", 0)
        record.setdefault("friendship", 0)
        record.setdefault("evolution", 0)
        record.setdefault("last_feed", "")
        record.setdefault("last_adventure", "")
    for pet_name, record in list(u["pet_collection"].items()):
        if not isinstance(record, dict):
            record = {}
            u["pet_collection"][pet_name] = record
        record.setdefault("level", 1)
        record.setdefault("exp", 0)
        record.setdefault("friendship", 0)
        record.setdefault("evolution", 0)
        record.setdefault("last_feed", "")
        record.setdefault("last_adventure", "")
        record["level"] = max(1, int(record.get("level", 1) or 1))
        record["exp"] = max(0, int(record.get("exp", 0) or 0))
        record["friendship"] = max(0, int(record.get("friendship", 0) or 0))
        record["evolution"] = max(0, min(2, int(record.get("evolution", 0) or 0)))
    if active_pet and active_pet in u["pet_collection"]:
        u["pet_level"] = u["pet_collection"][active_pet]["level"]

    if not isinstance(u.get("materials"), dict):
        u["materials"] = {}
    for material in ["강화석", "강화보호권", "옵션재설정권"]:
        u["materials"].setdefault(material, 0)
    if not isinstance(u.get("titles"), list):
        u["titles"] = ["신입 생존자"]
    if u.get("title") not in u["titles"]:
        u["titles"].append(u.get("title", "신입 생존자"))

    ensure_dungeon_user_state(u)
    ensure_vitals(u)
    ensure_conditions(u)
    return u


for uid in list(user_data.keys()):
    if isinstance(user_data[uid], dict):
        migrate_user(user_data[uid])

save_data()


def get_user(user_id):
    user_id = str(user_id)
    if user_id not in user_data:
        return None
    return migrate_user(user_data[user_id])


async def send_pages(channel, text, limit=MAX_MESSAGE_LENGTH):
    lines = text.split("\n")
    current = ""

    for line in lines:
        candidate = current + line + "\n"
        if len(candidate) > limit:
            if current:
                await channel.send(current.rstrip())
            current = line + "\n"
        else:
            current = candidate

    if current:
        await channel.send(current.rstrip())


async def check_registered(ctx):
    u = get_user(ctx.author.id)
    if u is None:
        await ctx.send(
            "⛔ **[출입 거부]** 아직 암시장 생존자 명부에 없습니다.\n"
            "`!가입 생존자`를 입력해 먼저 등록하세요."
        )
        return False
    ensure_daily_quest(u)
    ensure_weekly_quest(u)
    ensure_season_pass(u)
    return True


# =========================================================
# 아이템 DB: 7티어 / 70종
# =========================================================
ITEM_DB = {
    "일반": {
        "몽둥이": {"price": 300, "power": 1, "desc": "주변에서 쉽게 구한 둔기"},
        "손전등": {"price": 350, "power": 1, "desc": "어두운 폐허에서 시야 확보"},
        "녹슨파이프": {"price": 450, "power": 2, "desc": "무겁지만 쓸 만한 철제 파이프"},
        "작업용장갑": {"price": 500, "power": 2, "desc": "손을 보호하는 기본 장갑"},
        "등산가방": {"price": 600, "power": 2, "desc": "보급품을 넉넉하게 운반"},
        "낡은헬멧": {"price": 650, "power": 3, "desc": "충격을 조금 줄여주는 헬멧"},
        "주방칼": {"price": 700, "power": 3, "desc": "짧지만 날카로운 근접 무기"},
        "신호탄": {"price": 800, "power": 3, "desc": "위기 때 적의 시선을 분산"},
        "방수우의": {"price": 850, "power": 3, "desc": "오염된 비를 막아준다"},
        "구급주머니": {"price": 900, "power": 4, "desc": "전투 후 응급 처치용"},
    },
    "고급": {
        "철근조각": {"price": 1200, "power": 4, "desc": "끝이 뾰족하게 부러진 철근"},
        "녹슨권총": {"price": 1500, "power": 5, "desc": "잼이 자주 걸리는 오래된 권총"},
        "소방도끼": {"price": 1800, "power": 6, "desc": "문과 감염자를 함께 부순다"},
        "야구보호대": {"price": 2000, "power": 6, "desc": "급조한 사지 방어구"},
        "수제석궁": {"price": 2300, "power": 7, "desc": "조용한 원거리 무기"},
        "경찰방패": {"price": 2500, "power": 7, "desc": "근접 공격을 막는 진압 방패"},
        "군용나이프": {"price": 2700, "power": 8, "desc": "날카롭게 갈린 생존용 나이프"},
        "방독면": {"price": 3000, "power": 8, "desc": "독성 포자와 가스를 걸러준다"},
        "응급키트": {"price": 3200, "power": 9, "desc": "부상을 빠르게 안정시킨다"},
        "경량방탄복": {"price": 3500, "power": 9, "desc": "가볍고 활동성이 좋은 방탄복"},
    },
    "희귀": {
        "전술샷건": {"price": 5000, "power": 11, "desc": "근거리 감염자 무리 제압"},
        "군용방탄조끼": {"price": 5500, "power": 12, "desc": "총탄과 이빨을 함께 막는다"},
        "쇠크로스보우": {"price": 6000, "power": 12, "desc": "고장 적고 강력한 석궁"},
        "전기충격봉": {"price": 6500, "power": 13, "desc": "감염자의 근육을 마비시킨다"},
        "소음권총": {"price": 7000, "power": 14, "desc": "소음을 줄인 은밀한 권총"},
        "강화전술복": {"price": 7500, "power": 14, "desc": "절단과 충격에 강한 전투복"},
        "열감지스코프": {"price": 8200, "power": 15, "desc": "연기 속에서도 목표를 추적"},
        "전투드론": {"price": 9000, "power": 16, "desc": "정찰과 화력 지원을 동시에"},
        "감염차단주사": {"price": 9800, "power": 17, "desc": "감염 진행을 늦추는 실험약"},
        "개조소총": {"price": 10500, "power": 18, "desc": "정밀 부품으로 개조한 돌격소총"},
    },
    "영웅": {
        "야간투시경": {"price": 14000, "power": 20, "desc": "완전한 암흑에서도 시야 확보"},
        "전술방패": {"price": 15000, "power": 21, "desc": "중화기 파편까지 막는 방패"},
        "폭발화살석궁": {"price": 16500, "power": 22, "desc": "폭발 화살을 발사하는 특수 석궁"},
        "대물저격총": {"price": 18000, "power": 24, "desc": "거대 변이체 장갑 관통"},
        "고주파검": {"price": 20000, "power": 25, "desc": "진동 칼날로 두꺼운 조직 절단"},
        "중장갑외골격": {"price": 22000, "power": 27, "desc": "힘과 방어력을 동시에 증폭"},
        "EMP수류탄": {"price": 23500, "power": 28, "desc": "기계형 감염체를 무력화"},
        "플라즈마권총": {"price": 25000, "power": 30, "desc": "실험실에서 회수한 에너지 무기"},
        "생체탐지기": {"price": 27000, "power": 31, "desc": "벽 너머 생체 반응 탐지"},
        "재생갑옷": {"price": 30000, "power": 33, "desc": "손상 부위가 서서히 복구되는 갑옷"},
    },
    "전설": {
        "화염방사기": {"price": 38000, "power": 36, "desc": "감염자 무리를 불태우는 광역 병기"},
        "파워조준경": {"price": 42000, "power": 38, "desc": "탄도 보정이 자동 적용되는 조준경"},
        "전술경장갑": {"price": 45000, "power": 40, "desc": "특수부대용 최첨단 방호 장비"},
        "레일건": {"price": 50000, "power": 43, "desc": "전자기력으로 금속탄을 초고속 발사"},
        "썬더해머": {"price": 55000, "power": 45, "desc": "충격파를 발생시키는 전기 해머"},
        "드래곤브레스": {"price": 60000, "power": 48, "desc": "고온 탄환을 뿜는 특수 산탄총"},
        "블랙팬텀슈트": {"price": 68000, "power": 50, "desc": "은폐 기능이 내장된 전투복"},
        "타이탄캐논": {"price": 75000, "power": 54, "desc": "거대 괴수 전용 중화기"},
        "심연의낫": {"price": 82000, "power": 58, "desc": "검은 에너지를 흡수하는 낫"},
        "불사조장갑": {"price": 90000, "power": 62, "desc": "치명상을 한 번 버틴다는 전설의 장갑"},
    },
    "신화": {
        "종말의검": {"price": 120000, "power": 70, "desc": "재앙의 날에 발견된 검"},
        "천벌의창": {"price": 135000, "power": 74, "desc": "번개를 끌어내리는 창"},
        "아크리액터갑옷": {"price": 150000, "power": 78, "desc": "소형 반응로가 장착된 강화복"},
        "공허포식자": {"price": 170000, "power": 82, "desc": "목표의 에너지를 흡수하는 소총"},
        "시간왜곡장치": {"price": 190000, "power": 86, "desc": "찰나의 시간을 느리게 만든다"},
        "불멸자의가면": {"price": 210000, "power": 90, "desc": "착용자의 공포를 제거한다"},
        "신경동기화드론": {"price": 230000, "power": 94, "desc": "생각만으로 조종하는 전투 드론"},
        "오메가레일건": {"price": 260000, "power": 100, "desc": "벙커 벽도 관통하는 최종병기"},
        "세계수혈청": {"price": 290000, "power": 105, "desc": "생체 능력을 극한까지 끌어올린다"},
        "아포칼립스코어": {"price": 330000, "power": 112, "desc": "그라운드 제로에서 회수한 핵심체"},
    },
    "유일": {
        "루시퍼의대검": {"price": 500000, "power": 130, "desc": "지옥군단장의 검. 단 하나만 존재"},
        "창세의방패": {"price": 560000, "power": 138, "desc": "모든 공격을 거부한다는 방패"},
        "절대영도포": {"price": 620000, "power": 146, "desc": "주변을 순간 동결시키는 초병기"},
        "차원절단기": {"price": 700000, "power": 155, "desc": "공간 자체를 베는 실험 무기"},
        "메시아의왕관": {"price": 780000, "power": 164, "desc": "감염 군체를 지배한다는 왕관"},
        "판도라의심장": {"price": 860000, "power": 175, "desc": "무한 동력을 내뿜는 생체 핵"},
        "심판자의낫": {"price": 950000, "power": 188, "desc": "대상의 생명력을 직접 끊는다"},
        "천공요새코어": {"price": 1050000, "power": 202, "desc": "이동식 요새의 중앙 동력원"},
        "태초의유전자": {"price": 1200000, "power": 218, "desc": "인간 진화의 금지된 샘플"},
        "종말통제키": {"price": 1500000, "power": 240, "desc": "세계 멸망 병기의 최종 제어 장치"},
    }
}

TIER_ORDER = ["일반", "고급", "희귀", "영웅", "전설", "신화", "유일"]
TIER_DROP_WEIGHT = {
    "일반": 40,
    "고급": 28,
    "희귀": 17,
    "영웅": 9,
    "전설": 4,
    "신화": 1.5,
    "유일": 0.5
}


def find_item(item_name):
    for tier, items in ITEM_DB.items():
        if item_name in items:
            return tier, items[item_name]
    return None, None


EQUIPMENT_SLOTS = ["무기", "방어구", "머리", "장갑", "신발", "반지", "목걸이"]
TIER_EMOJI = {"일반": "⚪", "고급": "🟢", "희귀": "🔵", "영웅": "🟣", "전설": "🟠", "신화": "🔴", "유일": "🌈"}
TIER_MULTIPLIER = {"일반": 1.0, "고급": 1.15, "희귀": 1.35, "영웅": 1.65, "전설": 2.0, "신화": 2.5, "유일": 3.2}

def get_item_slot(item_name):
    name = item_name.lower()
    if any(k in name for k in ["반지", "링"]):
        return "반지"
    if any(k in name for k in ["목걸이", "팬던트", "부적"]):
        return "목걸이"
    if any(k in name for k in ["장갑", "글러브"]):
        return "장갑"
    if any(k in name for k in ["신발", "부츠", "군화"]):
        return "신발"
    if any(k in name for k in ["헬멧", "모자", "고글", "마스크"]):
        return "머리"
    if any(k in name for k in ["조끼", "갑옷", "방탄복", "우의", "코트", "재킷", "가방"]):
        return "방어구"
    return "무기"

def get_item_stats(item_name):
    tier, info = find_item(item_name)
    if not info:
        return {}
    slot = get_item_slot(item_name)
    mult = TIER_MULTIPLIER.get(tier, 1.0)
    power = max(1, int(info["power"] * mult))
    stats = {"공격력": 0, "방어력": 0, "치명타": 0, "회피": 0, "감염저항": 0, "행운": 0}
    if slot == "무기":
        stats["공격력"] = power
        stats["치명타"] = max(0, int(mult * 2) - 1)
    elif slot == "방어구":
        stats["방어력"] = power
        stats["감염저항"] = max(1, int(mult * 3))
    elif slot == "머리":
        stats["방어력"] = max(1, power // 2)
        stats["감염저항"] = max(1, int(mult * 2))
    elif slot == "장갑":
        stats["공격력"] = max(1, power // 2)
        stats["치명타"] = max(1, int(mult * 2))
    elif slot == "신발":
        stats["방어력"] = max(1, power // 3)
        stats["회피"] = max(1, int(mult * 2))
    elif slot == "반지":
        stats["치명타"] = max(1, int(mult * 3))
        stats["행운"] = max(1, int(mult * 2))
    elif slot == "목걸이":
        stats["감염저항"] = max(1, int(mult * 3))
        stats["행운"] = max(1, int(mult * 2))
    return stats

def equipment_totals(u):
    totals = {"공격력": 0, "방어력": 0, "치명타": 0, "회피": 0, "감염저항": 0, "행운": 0}
    for item_name in u.get("equipment", {}).values():
        if not item_name:
            continue
        stats = get_item_stats(item_name)
        enhance = u.get("enhancements", {}).get(item_name, 0)
        condition_mult = equipment_condition_multiplier(u, item_name)
        for key, value in stats.items():
            raw = value + (enhance if key in ["공격력", "방어력"] else enhance // 5)
            totals[key] += int(raw * condition_mult)
        for key, value in equipment_mod_stat_bonus(u, item_name).items():
            if key in totals:
                totals[key] += int(value)
    return totals


def item_power_for_user(u, item_name):
    _, item = find_item(item_name)
    if not item:
        return 0
    enhance = u.get("enhancements", {}).get(item_name, 0)
    base = item["power"] + enhance * max(1, int(item["power"] * 0.08))
    return max(0, int(base * equipment_condition_multiplier(u, item_name)) + equipment_mod_power_bonus(u, item_name))


def calculate_user_power(u):
    power = u["level"] * 2
    equipped = [x for x in u.get("equipment", {}).values() if x]
    for item_name in equipped:
        power += item_power_for_user(u, item_name)

    totals = equipment_totals(u)
    power += totals["공격력"] + totals["방어력"] // 2

    # V2.1 장비 랜덤 옵션 및 세트 효과
    for item_name in equipped:
        options = u.get("equipment_options", {}).get(item_name, {})
        power += int(options.get("공격력", 0))
        power += int(options.get("방어력", 0)) // 2
        power += int(options.get("치명타", 0)) + int(options.get("회피", 0))
    set_rules = [
        (["타이탄", "중장갑"], 2, 24),
        (["심연", "공허"], 2, 26),
        (["천공", "오메가"], 2, 25),
        (["종말", "아포칼립스"], 2, 35),
    ]
    for keywords, need, bonus in set_rules:
        count = sum(1 for item in equipped if any(keyword in item for keyword in keywords))
        if count >= need:
            power += bonus

    if u.get("pet"):
        power += get_pet_power(u)

    job_name = u.get("job")
    if job_name in JOBS:
        power += JOBS[job_name]["power_bonus"]

    return power


# =========================================================
# 괴물 DB: 난이도별 20종 / 총 80종
# =========================================================
DUNGEONS = {
    "약함": {
        "name": "버려진 지하철 / 도심 골목",
        "base_power": 5,
        "reward": 800,
        "drop_tiers": ["일반", "고급"],
        "monsters": [
            {"name": "굶주린 들개 무리", "desc": "빠르지만 체력이 약한 야생 동물"},
            {"name": "부패한 방랑자", "desc": "느리지만 방심하면 물리는 초기 감염자"},
            {"name": "거대 들쥐 떼", "desc": "시체를 파먹어 비대해진 쥐 무리"},
            {"name": "비틀거리는 노숙자 좀비", "desc": "소리에 반응해 다가오는 감염자"},
            {"name": "변이 길고양이", "desc": "민첩하게 목을 노리는 감염 동물"},
            {"name": "악취 구더기 떼", "desc": "장비 틈새로 파고드는 벌레"},
            {"name": "폐허의 약탈자 잔당", "desc": "굶주림에 이성을 잃은 인간"},
            {"name": "미쳐버린 까마귀", "desc": "눈을 노리고 급강하하는 조류"},
            {"name": "유리조각 부상자", "desc": "고통에 미쳐 날뛰는 감염체"},
            {"name": "감염된 우체부", "desc": "무거운 우편 가방을 휘두른다"},
            {"name": "폐허의 청소부", "desc": "날카로운 집게를 무기로 사용"},
            {"name": "돌연변이 비둘기 떼", "desc": "분진과 바이러스를 흩뿌린다"},
            {"name": "감염된 순찰견", "desc": "명령 없이도 집요하게 추격한다"},
            {"name": "독침 벌레", "desc": "붓기와 마비를 일으키는 독침"},
            {"name": "피투성이 학생", "desc": "책가방 속 물건을 마구 던진다"},
            {"name": "변이 너구리", "desc": "쓰레기 더미에서 갑자기 튀어나온다"},
            {"name": "하수구 악어", "desc": "도심 지하에서 비대해진 포식자"},
            {"name": "떠돌이 사냥꾼", "desc": "생존자를 먹잇감으로 보는 인간"},
            {"name": "감염된 배달기사", "desc": "오토바이 헬멧 때문에 머리가 단단하다"},
            {"name": "골목의 덫사냥꾼", "desc": "녹슨 철사 덫을 설치한다"},
        ]
    },
    "보통": {
        "name": "침식된 군부대 / 외곽 하수구",
        "base_power": 20,
        "reward": 3000,
        "drop_tiers": ["고급", "희귀"],
        "monsters": [
            {"name": "완력형 감염자 러너", "desc": "소리를 듣고 폭주하는 돌연변이"},
            {"name": "방독면 군인 좀비", "desc": "군장 때문에 방어력이 높다"},
            {"name": "스크리머", "desc": "비명으로 주변 감염자를 불러모은다"},
            {"name": "철근을 든 거한", "desc": "괴력으로 방어를 무너뜨린다"},
            {"name": "하수구 독성 슬라임", "desc": "장비를 부식시키는 액체 괴물"},
            {"name": "군견 케르베로스", "desc": "머리가 둘로 갈라진 군견 감염체"},
            {"name": "폭동진압 경찰 좀비", "desc": "단단한 방패를 들고 전진한다"},
            {"name": "감염된 간호사", "desc": "예측하기 어려운 동작으로 급습"},
            {"name": "소방수 돌연변이", "desc": "방화복 때문에 화염에 강하다"},
            {"name": "전기 파동 변이체", "desc": "접근한 장비를 오작동시킨다"},
            {"name": "브루트", "desc": "벽을 부수며 돌진하는 육중한 감염자"},
            {"name": "체인톱 광신도", "desc": "고통을 느끼지 않는 인간 약탈자"},
            {"name": "고장난 군용 드론", "desc": "적아 식별 없이 총탄을 난사한다"},
            {"name": "돌연변이 흑곰", "desc": "두꺼운 지방층으로 탄환을 버틴다"},
            {"name": "감염된 특공대원", "desc": "훈련된 전투 습관이 남아 있다"},
            {"name": "바이오 실험체 B-12", "desc": "불완전한 재생 능력을 지녔다"},
            {"name": "포자 살포자", "desc": "시야를 가리는 감염 포자를 퍼뜨린다"},
            {"name": "독가스 감염체", "desc": "죽을 때 유독가스를 뿜는다"},
            {"name": "중장갑 경비병", "desc": "방탄판을 여러 겹 덧댄 감염자"},
            {"name": "블러드 헌터", "desc": "피 냄새를 따라 끝까지 추적한다"},
        ]
    },
    "강함": {
        "name": "지하 연구소 폐허 / 오염된 병원",
        "base_power": 55,
        "reward": 10000,
        "drop_tiers": ["희귀", "영웅", "전설"],
        "monsters": [
            {"name": "변이된 거대 괴수 탱크", "desc": "일반 총알을 튕기는 근육 괴수"},
            {"name": "스토커", "desc": "빛을 굴절시키며 은폐한다"},
            {"name": "산성 침뱉기 돌연변이", "desc": "부식성 액체를 원거리 발사"},
            {"name": "철갑 호위병", "desc": "전신에 철판을 용접한 감염자"},
            {"name": "프로젝트 0호기", "desc": "최초의 인간형 생체 병기"},
            {"name": "신경 독소 살포충", "desc": "마비 가스를 뿜는 거대 곤충"},
            {"name": "그림자 암살자", "desc": "빛이 없는 곳에서 순간 이동"},
            {"name": "광란의 연구원", "desc": "수술 도구로 급소를 노린다"},
            {"name": "고열 방출형 변이체", "desc": "주변 온도를 비정상적으로 상승"},
            {"name": "폭탄 내장형 자폭병", "desc": "근접하면 체내 폭약이 폭발한다"},
            {"name": "데스 리퍼", "desc": "낫 모양 골격으로 생존자를 절단"},
            {"name": "타락한 기사", "desc": "실험용 외골격에 융합된 병사"},
            {"name": "심연의 집행관", "desc": "정신을 압박하는 저주파를 방출"},
            {"name": "플레임 비스트", "desc": "몸에서 인화성 체액을 뿜는다"},
            {"name": "크림슨 헌터", "desc": "상처 입은 적에게 더욱 빨라진다"},
            {"name": "블랙 팬텀", "desc": "전자 장비의 탐지를 회피한다"},
            {"name": "타이탄 Mk-II", "desc": "기계 장갑과 생체 조직이 결합"},
            {"name": "생체 병기 오메가", "desc": "다양한 감염체 능력을 복제한다"},
            {"name": "헬 브루트", "desc": "폭발에도 멈추지 않는 거대 감염자"},
            {"name": "네크로맨서", "desc": "죽은 감염체의 신경을 재가동한다"},
        ]
    },
    "지옥": {
        "name": "그라운드 제로 지하벙커",
        "base_power": 120,
        "reward": 30000,
        "drop_tiers": ["영웅", "전설", "신화", "유일"],
        "monsters": [
            {"name": "학살자 아포칼립스 퀸", "desc": "모든 감염자의 정점"},
            {"name": "오염된 메카 타이란트", "desc": "폭주한 생체 기계 병기"},
            {"name": "군단장 둠브링어", "desc": "주변 공기를 얼리는 초위험체"},
            {"name": "차원 왜곡형 초월자", "desc": "공간을 일그러뜨려 공격을 회피"},
            {"name": "불멸의 하이드라 가디언", "desc": "머리가 잘려도 재생한다"},
            {"name": "지옥의 화염 악마", "desc": "검붉은 용암을 두른 파괴자"},
            {"name": "사이킥 마인드 브레이커", "desc": "정신 공격으로 의지를 꺾는다"},
            {"name": "붕괴된 실험체의 신", "desc": "수많은 시체가 융합된 괴물"},
            {"name": "종말의 메시아", "desc": "멸망을 선고하는 정체불명의 재앙"},
            {"name": "앱솔루트 제로 타이탄", "desc": "절대 영도의 냉기를 방출"},
            {"name": "루시퍼의 사도", "desc": "검은 날개로 초고속 돌진"},
            {"name": "지옥군단 사령관", "desc": "주변 감염체를 전술적으로 지휘"},
            {"name": "심판자", "desc": "생명 반응을 지우는 광선을 발사"},
            {"name": "공허의 군주", "desc": "주변 에너지를 빨아들인다"},
            {"name": "혼돈의 용", "desc": "산성과 화염을 동시에 토한다"},
            {"name": "데스킹", "desc": "죽을수록 더 강해지는 왕"},
            {"name": "종말의 사신", "desc": "방어구를 무시하는 낫을 휘두른다"},
            {"name": "심연의 여왕", "desc": "환각으로 동료와 적을 뒤바꾼다"},
            {"name": "타락한 천사", "desc": "신성한 외형을 한 살육 병기"},
            {"name": "악마황", "desc": "그라운드 제로 최심부의 절대자"},
        ]
    }
}


# =========================================================
# 랜덤 인사말 60개
# =========================================================
GREETINGS = [
    "오늘도 살아남았군.",
    "암시장은 언제나 열려 있다.",
    "살아 있는 게 기적인 세상이야.",
    "피 냄새가 진동하는군.",
    "또 식량 벌러 왔나?",
    "총알은 충분한가?",
    "어젯밤에도 생존자 한 명이 사라졌어.",
    "감염자보다 사람이 더 무서운 법이지.",
    "환영한다, 생존자.",
    "목소리 낮춰. 놈들이 듣는다.",
    "`!가입 생존자`는 했겠지?",
    "오늘은 전설 장비가 나올지도 모르지.",
    "방아쇠에 손가락 올리고 다녀.",
    "남쪽 골목은 가지 마. 느낌이 안 좋아.",
    "무전기에 이상한 신호가 잡혔다.",
    "자네 뒤에 있는 건 동료가 맞나?",
    "암시장 물건은 환불 불가다.",
    "빚부터 갚아. 사채업자가 널 찾고 있어.",
    "던전에 갈 거면 유언부터 남겨.",
    "오늘 출석 보급은 챙겼나?",
    "한 번의 방심이 감염으로 이어진다.",
    "장비가 너무 허술한데 살아 돌아오겠어?",
    "뭔가 타는 냄새가 나는데.",
    "그라운드 제로에서 신호가 들어왔다.",
    "레이드 인원이 필요해 보이는군.",
    "펫은 귀엽다고 방심하면 안 돼.",
    "강화는 욕심내는 순간 터지는 법이지.",
    "제작대가 비어 있다. 뭘 만들 생각인가?",
    "오늘의 퀘스트부터 확인해.",
    "랭킹은 냉정하다. 강한 자만 남지.",
    "식량이 곧 목숨이다.",
    "소음은 곧 죽음이다.",
    "운이 나쁘면 약한 던전에서도 끝난다.",
    "좋은 장비는 살아남은 자의 특권이지.",
    "저쪽 벽에서 긁는 소리 안 들리나?",
    "대답하지 마. 네 목소리를 흉내 내는 놈일 수 있어.",
    "창고 문을 세 번 두드리면 절대 열지 마.",
    "누군가 무전으로 네 이름을 부르더군.",
    "빛이 깜빡이면 즉시 자리를 떠.",
    "오늘은 공기가 유난히 썩었군.",
    "죽은 줄 알았는데 또 왔네.",
    "레벨만 믿지 마. 장비가 더 중요할 때도 있다.",
    "전투력은 거짓말하지 않는다.",
    "크리티컬 한 방이면 전세가 뒤집히지.",
    "회피에 실패하면 바로 저녁 식사가 된다.",
    "희귀 드롭은 준비된 자에게 온다.",
    "보스가 다시 깨어났다는 소문이 있다.",
    "월드보스가 뜨면 모두가 적이자 동료다.",
    "암시장 규칙은 하나다. 먼저 살아남아.",
    "감염은 빠르고 치료는 느리다.",
    "사람을 믿되 탄창은 확인해.",
    "오늘은 날씨보다 감염 지수가 더 위험하다.",
    "네 그림자가 하나 더 많은 것 같은데?",
    "기분 탓이겠지. 아마도.",
    "바닥의 핏자국을 따라가지 마.",
    "낡은 엘리베이터는 지하 13층에서 멈춘다.",
    "보급품 상자에 손이 달려 있었다는 소문이야.",
    "오늘도 목숨값은 싸고 탄약값은 비싸다.",
    "살고 싶으면 팀을 만들고, 강해지고 싶으면 경쟁해.",
    "어서 와. 종말은 아직 끝나지 않았다."
]


# =========================================================
# 펫 / 제작 / 업적 / 칭호
# =========================================================
PET_DB = {
    "폐허쥐": {
        "emoji": "🐀", "rarity": "일반", "price": 5000, "power": 3,
        "desc": "재료 냄새를 기가 막히게 찾아내는 작은 생존 동료",
        "skill": "수집 본능",
        "skill_desc": "던전 승리 시 추가 재료를 발견할 확률이 증가합니다.",
        "evolutions": ["폐허쥐", "철니 폐허쥐", "군체의 왕"],
        "bonuses": {"material": 0.12},
    },
    "정찰까마귀": {
        "emoji": "🐦‍⬛", "rarity": "고급", "price": 50000, "power": 7,
        "desc": "높은 곳에서 적의 빈틈과 이동 경로를 먼저 찾아냅니다.",
        "skill": "급소 탐지",
        "skill_desc": "던전 전투의 치명타 확률이 증가합니다.",
        "evolutions": ["정찰까마귀", "야간정찰 까마귀", "검은 감시자"],
        "bonuses": {"crit": 0.04},
    },
    "군견제로": {
        "emoji": "🐕", "rarity": "희귀", "price": 120000, "power": 13,
        "desc": "군부대 출신의 충직한 군견. 전투 중 주인을 끝까지 지킵니다.",
        "skill": "전투 지원",
        "skill_desc": "던전 승리 확률이 소폭 증가합니다.",
        "evolutions": ["군견제로", "강화군견 제로", "전쟁견 제로"],
        "bonuses": {"victory": 0.04},
    },
    "변이살쾡이": {
        "emoji": "🐈", "rarity": "영웅", "price": 300000, "power": 22,
        "desc": "소리 없이 움직이며 치명적인 공격을 피하게 돕는 포식자",
        "skill": "그림자 보행",
        "skill_desc": "던전 전투의 회피 확률이 증가합니다.",
        "evolutions": ["변이살쾡이", "그림자 살쾡이", "야수왕"],
        "bonuses": {"dodge": 0.05},
    },
    "미니드론": {
        "emoji": "🤖", "rarity": "전설", "price": 750000, "power": 34,
        "desc": "전투 기록을 분석하고 가치 있는 보급품을 선별하는 소형 드론",
        "skill": "보급 분석",
        "skill_desc": "던전에서 획득하는 식량 보상이 증가합니다.",
        "evolutions": ["미니드론", "전투드론", "오메가 드론"],
        "bonuses": {"reward": 0.08},
    },
    "어린하이드라": {
        "emoji": "🐍", "rarity": "신화", "price": 1800000, "power": 55,
        "desc": "재생 능력을 나누어 주인의 상처를 조금씩 회복시킵니다.",
        "skill": "재생 세포",
        "skill_desc": "던전 승리 후 잃은 HP를 일부 회복합니다.",
        "evolutions": ["어린하이드라", "삼두 하이드라", "재생의 군주"],
        "bonuses": {"heal": 4},
    },
    "공허의새끼용": {
        "emoji": "🐉", "rarity": "초월", "price": 5000000, "power": 90,
        "desc": "공간 에너지를 먹고 자라며 전투와 탐색 전반을 강화하는 희귀 용",
        "skill": "공허 공명",
        "skill_desc": "치명타, 회피, 보상, 재료 발견과 회복을 모두 강화합니다.",
        "evolutions": ["공허의새끼용", "공허의 비룡", "차원룡"],
        "bonuses": {"crit": 0.03, "dodge": 0.03, "reward": 0.05, "material": 0.08, "heal": 3, "victory": 0.02},
    },
    '아바돈': {
        "emoji": '🐶', "rarity": '일반', "price": 6500, "power": 4,
        "desc": '별빛 목걸이를 찬 복슬복슬한 강아지 동료. 곁에 있는 것만으로도 생존자의 마음을 안정시킵니다.',
        "skill": '따뜻한 응원',
        "skill_desc": '던전 승리 후 잃은 HP를 조금 회복합니다.',
        "evolutions": ['아바돈', '성광 아바돈', '천상의 아바돈'],
        "bonuses": {'heal': 2},
    },
    '다크프': {
        "emoji": '🐺', "rarity": '고급', "price": 60000, "power": 8,
        "desc": '검은 털과 붉은 장식을 지닌 장난꾸러기 그림자 늑대. 위험을 먼저 감지합니다.',
        "skill": '그림자 감각',
        "skill_desc": '던전 전투의 회피 확률이 증가합니다.',
        "evolutions": ['다크프', '그림자 다크프', '심연왕 다크프'],
        "bonuses": {'dodge': 0.035},
    },
    '루나냥': {
        "emoji": '🐱', "rarity": '고급', "price": 70000, "power": 9,
        "desc": '초승달 장식을 달고 다니는 새하얀 고양이. 어둠 속 작은 빈틈을 찾아냅니다.',
        "skill": '월광 시야',
        "skill_desc": '던전 전투의 치명타 확률이 증가합니다.',
        "evolutions": ['루나냥', '월광 루나냥', '달의 여제 루나냥'],
        "bonuses": {'crit': 0.035},
    },
    '파이어몽': {
        "emoji": '🐒', "rarity": '희귀', "price": 140000, "power": 14,
        "desc": '꼬리 끝에 따뜻한 불꽃을 품은 아기 원숭이. 전투가 길어질수록 용기를 북돋습니다.',
        "skill": '불꽃 응원',
        "skill_desc": '던전 승리 확률이 소폭 증가합니다.',
        "evolutions": ['파이어몽', '화염 파이어몽', '태양왕 파이어몽'],
        "bonuses": {'victory': 0.035},
    },
    '스노우씨': {
        "emoji": '🐰', "rarity": '희귀', "price": 160000, "power": 16,
        "desc": '눈송이처럼 포근한 흰 토끼. 차가운 기운으로 상처와 피로를 가라앉힙니다.',
        "skill": '설원의 숨결',
        "skill_desc": '던전 승리 후 잃은 HP를 회복합니다.',
        "evolutions": ['스노우씨', '설원 스노우씨', '빙설의 수호자'],
        "bonuses": {'heal': 4},
    },
    '메카로보': {
        "emoji": '🤖', "rarity": '희귀', "price": 180000, "power": 17,
        "desc": '토끼 귀 안테나와 푸른 눈을 가진 소형 로봇. 보급품의 가치를 빠르게 분석합니다.',
        "skill": '정밀 스캔',
        "skill_desc": '던전에서 획득하는 식량 보상이 증가합니다.',
        "evolutions": ['메카로보', '강화 메카로보', '오메가 메카로보'],
        "bonuses": {'reward': 0.05},
    },
    '썬더드래곤': {
        "emoji": '🐲', "rarity": '영웅', "price": 350000, "power": 24,
        "desc": '번개 날개를 가진 작고 씩씩한 용. 전장의 흐름을 읽고 강한 일격을 돕습니다.',
        "skill": '뇌광 공명',
        "skill_desc": '던전의 치명타 확률과 승리 확률을 함께 강화합니다.',
        "evolutions": ['썬더드래곤', '뇌광 썬더드래곤', '폭풍룡'],
        "bonuses": {'crit': 0.025, 'victory': 0.02},
    },
    '포레스트': {
        "emoji": '🦌', "rarity": '영웅', "price": 400000, "power": 26,
        "desc": '새싹 뿔과 잎사귀 꼬리를 가진 숲의 정령. 재료의 기운과 생명력을 감지합니다.',
        "skill": '숲의 축복',
        "skill_desc": '추가 재료 발견과 전투 후 회복을 함께 강화합니다.',
        "evolutions": ['포레스트', '숲의 포레스트', '세계수의 정령'],
        "bonuses": {'material': 0.08, 'heal': 2},
    },
    '미니골렘': {
        "emoji": '🗿', "rarity": '전설', "price": 850000, "power": 37,
        "desc": '고대 석판과 푸른 핵으로 움직이는 작은 골렘. 단단한 몸으로 앞길을 지켜줍니다.',
        "skill": '대지의 방벽',
        "skill_desc": '던전 승리 확률을 높이고 획득 보상을 조금 증가시킵니다.',
        "evolutions": ['미니골렘', '강화 미니골렘', '대지의 거신'],
        "bonuses": {'victory': 0.03, 'reward': 0.03},
    },
    '유니콘': {
        "emoji": '🦄', "rarity": '신화', "price": 2100000, "power": 59,
        "desc": '무지갯빛 갈기와 별빛 뿔을 지닌 신비로운 동료. 생존자의 행운과 회복을 돕습니다.',
        "skill": '성휘의 기적',
        "skill_desc": '던전 보상과 전투 후 회복을 크게 강화합니다.',
        "evolutions": ['유니콘', '성휘 유니콘', '별무리 유니콘'],
        "bonuses": {'reward': 0.06, 'heal': 5},
    },
    '헤르메스': {
        "emoji": '🪽', "rarity": '신화', "price": 2400000, "power": 63,
        "desc": '작은 날개와 얼음빛 장식을 가진 하늘의 전령. 빠른 움직임으로 위험과 보물을 먼저 찾습니다.',
        "skill": '천공의 전령',
        "skill_desc": '회피 확률과 식량 보상을 함께 강화합니다.',
        "evolutions": ['헤르메스', '천공 헤르메스', '신속의 사자'],
        "bonuses": {'dodge': 0.04, 'reward': 0.05},
    },
    '네온문': {
        "emoji": '🌙', "rarity": '초월', "price": 5500000, "power": 94,
        "desc": '보랏빛 달 그림자를 두른 검은 고양이. 공허의 기운으로 탐색과 전투 전반을 증폭합니다.',
        "skill": '네온 월식',
        "skill_desc": '치명타·회피·보상·재료 발견과 회복을 모두 강화합니다.',
        "evolutions": ['네온문', '월영 네온문', '공허월의 군주'],
        "bonuses": {'crit': 0.025, 'dodge': 0.025, 'reward': 0.045, 'material': 0.065, 'heal': 3, 'victory': 0.015},
    },
}

PET_MAX_LEVEL = 50
PET_MAX_EVOLUTION = 2
PET_FEED_COOLDOWN_MINUTES = 30
PET_ADVENTURE_COOLDOWN_MINUTES = 60
PET_RARITY_ORDER = {"일반": 1, "고급": 2, "희귀": 3, "영웅": 4, "전설": 5, "신화": 6, "초월": 7}


def _new_pet_record(level=1):
    return {
        "level": max(1, int(level or 1)),
        "exp": 0,
        "friendship": 0,
        "evolution": 0,
        "last_feed": "",
        "last_adventure": "",
    }


def _parse_pet_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def ensure_pet_collection(u):
    collection = u.setdefault("pet_collection", {})
    if not isinstance(collection, dict):
        collection = {}
        u["pet_collection"] = collection

    active = u.get("pet")
    if active:
        record = collection.setdefault(active, _new_pet_record(u.get("pet_level", 1)))
        if not isinstance(record, dict):
            record = _new_pet_record(u.get("pet_level", 1))
            collection[active] = record
        record["level"] = max(int(record.get("level", 1) or 1), int(u.get("pet_level", 1) or 1))

    for name, record in list(collection.items()):
        if not isinstance(record, dict):
            record = _new_pet_record()
            collection[name] = record
        defaults = _new_pet_record(record.get("level", 1))
        for key, value in defaults.items():
            record.setdefault(key, value)
        record["level"] = max(1, min(PET_MAX_LEVEL, int(record.get("level", 1) or 1)))
        record["exp"] = max(0, int(record.get("exp", 0) or 0))
        record["friendship"] = max(0, int(record.get("friendship", 0) or 0))
        record["evolution"] = max(0, min(PET_MAX_EVOLUTION, int(record.get("evolution", 0) or 0)))

    if active and active not in PET_DB:
        u["pet"] = None
        u["pet_level"] = 1
    elif active and active in collection:
        u["pet_level"] = collection[active]["level"]
    return collection


def get_pet_record(u, pet_name=None):
    collection = ensure_pet_collection(u)
    name = pet_name or u.get("pet")
    if not name or name not in collection or name not in PET_DB:
        return None, None
    return name, collection[name]


def get_pet_display_name(pet_name, record):
    info = PET_DB.get(pet_name, {})
    evolutions = info.get("evolutions", [pet_name])
    stage = max(0, min(len(evolutions) - 1, int(record.get("evolution", 0) or 0)))
    return evolutions[stage]


def get_pet_power(u, pet_name=None):
    name, record = get_pet_record(u, pet_name)
    if not name:
        return 0
    info = PET_DB[name]
    level = record["level"]
    evolution = record["evolution"]
    evolution_bonus = int(info["power"] * 0.35 * evolution) + evolution * 5
    return info["power"] + (level - 1) * 2 + evolution_bonus


def get_pet_bonuses(u):
    name, record = get_pet_record(u)
    empty = {"crit": 0.0, "dodge": 0.0, "reward": 0.0, "material": 0.0, "heal": 0, "victory": 0.0}
    if not name:
        return empty

    level = record["level"]
    evolution = record["evolution"]
    scale = 1.0 + (level - 1) * 0.012 + evolution * 0.25
    raw = PET_DB[name].get("bonuses", {})
    result = empty.copy()
    for key in ["crit", "dodge", "reward", "material", "victory"]:
        result[key] = min(0.25, float(raw.get(key, 0)) * scale)
    result["heal"] = max(0, int(float(raw.get("heal", 0)) * scale))
    # 모든 펫은 성장에 따라 아주 작은 기본 회피 보너스를 얻습니다.
    result["dodge"] = min(0.25, result["dodge"] + min(0.05, level * 0.001))
    return result


def pet_exp_required(level):
    return 60 + max(1, int(level)) * 20


def gain_pet_exp(u, amount):
    name, record = get_pet_record(u)
    if not name or amount <= 0:
        return 0

    record["exp"] += int(amount)
    level_ups = 0
    while record["level"] < PET_MAX_LEVEL:
        required = pet_exp_required(record["level"])
        if record["exp"] < required:
            break
        record["exp"] -= required
        record["level"] += 1
        level_ups += 1
    if record["level"] >= PET_MAX_LEVEL:
        record["level"] = PET_MAX_LEVEL
        record["exp"] = 0
    u["pet_level"] = record["level"]
    return level_ups


def pet_cooldown_remaining(record, key, minutes):
    last = _parse_pet_time(record.get(key))
    if not last:
        return 0
    remaining = int((last + timedelta(minutes=minutes) - datetime.now()).total_seconds())
    return max(0, remaining)


def format_seconds(seconds):
    if seconds <= 0:
        return "사용 가능"
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}분 {seconds}초"


MATERIALS = ["철조각", "화약", "전자부품", "생체조직", "에너지코어", "고대파편"]

# 던전 기본 재료 전용 드롭 테이블.
# V2.1 모듈이 MATERIALS에 강화석 계열 재료를 추가하므로,
# 고정 길이 weights와 공유 목록을 함께 사용하면 개수가 달라질 수 있다.
DUNGEON_MATERIAL_DROP_WEIGHTS = {
    "철조각": 35,
    "화약": 25,
    "전자부품": 20,
    "생체조직": 12,
    "에너지코어": 6,
    "고대파편": 2,
}

CRAFT_RECIPES = {
    "응급키트": {"철조각": 2, "생체조직": 1},
    "수제석궁": {"철조각": 4, "전자부품": 1},
    "전기충격봉": {"철조각": 4, "전자부품": 3},
    "EMP수류탄": {"화약": 4, "전자부품": 5},
    "플라즈마권총": {"전자부품": 8, "에너지코어": 2},
    "레일건": {"철조각": 12, "전자부품": 12, "에너지코어": 4},
    "공허포식자": {"생체조직": 15, "에너지코어": 8, "고대파편": 3},
    "차원절단기": {"에너지코어": 20, "고대파편": 15},
}

CRAFT_FAILURE_COST_MIN = 120
CRAFT_FAILURE_COST_MAX = 1_500


def craft_failure_chance(recipe):
    """간단 장비 약 9%, 최상위 장비 약 19% 범위의 제작 실패 확률입니다."""
    total_materials = sum(max(0, int(amount)) for amount in recipe.values())
    complexity = total_materials + len(recipe) * 2
    return min(0.20, 0.07 + complexity * 0.003)


def craft_failure_cost(balance, recipe):
    balance = max(0, int(balance))
    if balance <= 0:
        return 0
    total_materials = sum(max(0, int(amount)) for amount in recipe.values())
    high = min(CRAFT_FAILURE_COST_MAX, 250 + total_materials * 35)
    low = min(CRAFT_FAILURE_COST_MIN, high)
    return min(balance, random.randint(low, high))


def ensure_crafting_v624(u):
    state = u.setdefault("crafting_v624", {})
    if not isinstance(state, dict):
        state = {}
        u["crafting_v624"] = state
    state.setdefault("failures", 0)
    state.setdefault("total_failure_cost", 0)
    state.setdefault("last_failure_item", "")
    return state


ACHIEVEMENTS = {
    "첫 승리": ("dungeon_wins", 1, "전투의 시작"),
    "숙련 사냥꾼": ("dungeon_wins", 25, "감염자 사냥꾼"),
    "학살자": ("dungeon_wins", 100, "백전노장"),
    "제작 입문": ("craft_count", 1, "손재주 좋은 생존자"),
    "대장장이": ("enhance_success", 10, "강화의 달인"),
    "부자": ("earned", 100000, "암시장 큰손"),
    "보스 사냥꾼": ("boss_damage", 5000, "보스 브레이커"),
    "세계의 수호자": ("worldboss_damage", 20000, "종말 저지자"),
}


def add_title(u, title):
    if title not in u["titles"]:
        u["titles"].append(title)


def check_achievements(u):
    unlocked = []
    for name, (stat_key, target, title) in ACHIEVEMENTS.items():
        if name in u["achievements"]:
            continue
        if u["stats"].get(stat_key, 0) >= target:
            u["achievements"].append(name)
            add_title(u, title)
            unlocked.append((name, title))
    return unlocked


def random_materials(difficulty):
    table = {
        "약함": (1, 2),
        "보통": (1, 3),
        "강함": (2, 4),
        "지옥": (3, 6)
    }
    count = random.randint(*table[difficulty])
    gained = {}
    material_names = list(DUNGEON_MATERIAL_DROP_WEIGHTS)
    material_weights = list(DUNGEON_MATERIAL_DROP_WEIGHTS.values())

    for _ in range(count):
        material = random.choices(
            material_names,
            weights=material_weights,
            k=1,
        )[0]
        gained[material] = gained.get(material, 0) + 1
    return gained


def give_materials(u, gained):
    for material, amount in gained.items():
        u["materials"][material] = u["materials"].get(material, 0) + amount


def select_drop(tiers):
    available_tiers = [tier for tier in tiers if tier in ITEM_DB]
    weights = [TIER_DROP_WEIGHT[tier] for tier in available_tiers]
    tier = random.choices(available_tiers, weights=weights, k=1)[0]
    item_name = random.choice(list(ITEM_DB[tier].keys()))
    return tier, item_name



# =========================================================
# 주간 퀘스트 / 시즌패스 공통 처리
# =========================================================
WEEKLY_QUEST_TYPES = [
    ("생활 활동", 20, 18000),
    ("PVP 참여", 5, 15000),
    ("파티 사냥", 5, 20000),
    ("던전 승리", 15, 22000),
]

SEASON_REWARDS = {
    1: {"points": 100, "food": 5000, "title": None},
    2: {"points": 250, "food": 12000, "title": None},
    3: {"points": 450, "food": 22000, "title": "시즌 개척자"},
    4: {"points": 700, "food": 35000, "title": None},
    5: {"points": 1000, "food": 55000, "title": "종말 시즌 정복자"},
    6: {"points": 1400, "food": 80000, "title": None},
    7: {"points": 1900, "food": 120000, "title": "아포칼립스 챔피언"},
}


def current_week_key():
    year, week, _ = datetime.now(timezone.utc).astimezone(KST).isocalendar()
    return f"{year}-W{week:02d}"


def ensure_weekly_quest(u):
    week = current_week_key()
    q = u["weekly_quest"]
    if q.get("week") == week:
        return

    qtype, target, reward = random.choice(WEEKLY_QUEST_TYPES)
    u["weekly_quest"] = {
        "week": week,
        "type": qtype,
        "target": target,
        "progress": 0,
        "reward": reward,
        "claimed": False
    }


def progress_weekly(u, quest_type, amount=1):
    ensure_weekly_quest(u)
    q = u["weekly_quest"]
    if q["type"] == quest_type and not q["claimed"]:
        q["progress"] = min(q["target"], q["progress"] + amount)


def ensure_season_pass(u):
    season = datetime.now(timezone.utc).astimezone(KST).strftime("%Y-%m")
    sp = u["season_pass"]
    if sp.get("season") != season:
        u["season_pass"] = {
            "season": season,
            "points": 0,
            "claimed_levels": []
        }


def add_season_points(u, amount):
    ensure_season_pass(u)
    u["season_pass"]["points"] += max(0, int(amount))

# =========================================================
# 일일 퀘스트
# =========================================================
QUEST_TYPES = [
    ("던전 승리", 3, 2500),
    ("도박 참여", 5, 2000),
    ("아이템 구매", 1, 3000),
    ("제작 성공", 1, 4000),
    ("강화 성공", 1, 5000),
]


def ensure_daily_quest(u):
    today = datetime.now(timezone.utc).astimezone(KST).strftime("%Y-%m-%d")
    q = u["daily_quest"]

    if q.get("date") == today:
        return

    qtype, target, reward = random.choice(QUEST_TYPES)
    u["daily_quest"] = {
        "date": today,
        "type": qtype,
        "target": target,
        "progress": 0,
        "reward": reward,
        "claimed": False
    }
    save_data()


def progress_quest(u, quest_type, amount=1):
    ensure_daily_quest(u)
    q = u["daily_quest"]

    if q["type"] == quest_type and not q["claimed"]:
        q["progress"] = min(q["target"], q["progress"] + amount)


# =========================================================
# 월드보스 / 서버 보스
# =========================================================
WORLD_BOSS_POOL = [
    {"name": "종말의 포식자 아바돈", "max_hp": 90000, "grade": "전설", "trait": "광폭화", "material": "생체조직"},
    {"name": "심연룡 네메시스", "max_hp": 120000, "grade": "전설", "trait": "재생", "material": "고대파편"},
    {"name": "기계신 타이란트-X", "max_hp": 150000, "grade": "신화", "trait": "중장갑", "material": "에너지코어"},
    {"name": "그라운드 제로의 군주", "max_hp": 180000, "grade": "신화", "trait": "감염폭풍", "material": "생체조직"},
    {"name": "붉은 여왕 이브", "max_hp": 220000, "grade": "유일", "trait": "피의 장막", "material": "고대파편"},
    {"name": "천공요새 파괴자 오메가", "max_hp": 260000, "grade": "유일", "trait": "전자 방벽", "material": "에너지코어"},
]


def create_world_boss(forced_name=None):
    selected = None
    if forced_name:
        for candidate in WORLD_BOSS_POOL:
            if forced_name.lower() in candidate["name"].lower():
                selected = candidate
                break
    selected = selected or random.choice(WORLD_BOSS_POOL)
    hp = selected["max_hp"]
    return {
        "name": selected["name"],
        "grade": selected["grade"],
        "trait": selected["trait"],
        "material": selected["material"],
        "max_hp": hp,
        "hp": hp,
        "participants": {},
        "status": "active",
        "spawned_at": datetime.now().isoformat(),
        "defeated_at": None,
    }


def migrate_world_boss(boss):
    if not isinstance(boss, dict) or not boss.get("name"):
        return create_world_boss()
    boss.setdefault("grade", "전설")
    boss.setdefault("trait", "알 수 없음")
    boss.setdefault("material", "고대파편")
    boss.setdefault("status", "defeated" if boss.get("hp", 0) <= 0 else "active")
    boss.setdefault("defeated_at", None)
    participants = boss.setdefault("participants", {})
    for uid, value in list(participants.items()):
        if isinstance(value, (int, float)):
            participants[uid] = {"damage": int(value), "attacks": 0, "last_hit": False}
        elif isinstance(value, dict):
            value.setdefault("damage", 0)
            value.setdefault("attacks", 0)
            value.setdefault("last_hit", False)
        else:
            participants[uid] = {"damage": 0, "attacks": 0, "last_hit": False}
    return boss


world_data["world_boss"] = migrate_world_boss(world_data.get("world_boss"))
world_data.setdefault("season", datetime.now().strftime("%Y-%m"))
world_data.setdefault("server_bosses", {})
world_data.setdefault("guilds", {})
world_data.setdefault("market", {})
world_data.setdefault("market_next_id", 1)
world_data.setdefault("parties", {})
save_data()


def get_server_boss(guild_id):
    guild_id = str(guild_id)
    bosses = world_data["server_bosses"]

    if guild_id not in bosses or bosses[guild_id]["hp"] <= 0:
        bosses[guild_id] = {
            "name": random.choice([
                "지하벙커의 폭군",
                "감염 군단장",
                "타이탄 실험체",
                "붉은 여왕"
            ]),
            "max_hp": 10000,
            "hp": 10000,
            "participants": {}
        }
        save_data()

    return bosses[guild_id]


# =========================================================
# V7.0.2 명령 트랜잭션 잠금 / 운영 계측
# =========================================================
class ConcurrentOperation(commands.CheckFailure):
    pass


_COMMAND_LOCKS = {}


def _release_command_lock(ctx):
    lock = getattr(ctx, "_abaddon_user_lock", None)
    if lock is not None and lock.locked():
        lock.release()
    setattr(ctx, "_abaddon_user_lock", None)


@bot.before_invoke
async def _v702_before_command(ctx):
    user_id = str(getattr(ctx.author, "id", "0"))
    lock = _COMMAND_LOCKS.setdefault(user_id, asyncio.Lock())
    try:
        await asyncio.wait_for(lock.acquire(), timeout=4.0)
    except asyncio.TimeoutError as exc:
        raise ConcurrentOperation("이전 명령 처리 중") from exc
    ctx._abaddon_user_lock = lock
    ctx._abaddon_started_monotonic = time.monotonic()
    recorder = getattr(bot, "v702_record_command_start", None)
    if callable(recorder):
        recorder(ctx)


@bot.after_invoke
async def _v702_after_command(ctx):
    try:
        if not bool(getattr(ctx, "command_failed", False)):
            recorder = getattr(bot, "v702_record_command_success", None)
            if callable(recorder):
                recorder(ctx, max(0.0, time.monotonic() - getattr(ctx, "_abaddon_started_monotonic", time.monotonic())))
    finally:
        _release_command_lock(ctx)


# =========================================================
# 이벤트
# =========================================================
@bot.event
async def on_ready():
    global _LAST_BACKUP_AT
    print(f"로그인 완료: {bot.user} / 서버 {len(bot.guilds)}개")
    if not getattr(bot, "_abaddon_v702_startup_checked", False):
        bot._abaddon_v702_startup_checked = True
        bot._abaddon_load_recovery_status = dict(_LOAD_RECOVERY_STATUS)
        try:
            snapshot = create_data_backup("startup")
            _LAST_BACKUP_AT = snapshot.get("modified_at", datetime.now().isoformat())
            bot._abaddon_startup_backup = snapshot
        except Exception as exc:
            bot._abaddon_startup_backup = {"valid": False, "error": f"{type(exc).__name__}: {exc}"}
            print(f"[시작 백업 경고] {type(exc).__name__}: {exc}", flush=True)

    if not getattr(bot, "_abaddon_slash_synced", False):
        now_ts = int(datetime.now().timestamp())
        retry_after = int(getattr(bot, "_abaddon_slash_sync_retry_after", 0) or 0)
        if now_ts >= retry_after:
            bot._abaddon_slash_sync_status = "syncing"
            bot._abaddon_slash_sync_error = ""
            bot._abaddon_slash_sync_at = datetime.now().isoformat()
            try:
                synced = await bot.tree.sync()
                bot._abaddon_slash_synced = True
                bot._abaddon_slash_sync_status = "success"
                bot._abaddon_slash_sync_count = len(synced)
                bot._abaddon_slash_sync_at = datetime.now().isoformat()
                bot._abaddon_slash_sync_retry_after = 0
                print(
                    f"슬래시 명령어 동기화 완료: "
                    f"최상위 {len(synced)}개 / 전체 {sum(1 for _ in bot.tree.walk_commands())}개"
                )
            except Exception as exc:
                raw_error = f"{type(exc).__name__}: {exc}"
                kind = discord_rate_guard.note_from_text(raw_error)
                delay = 600 if kind in {"1015", "429"} else 300
                bot._abaddon_slash_sync_retry_after = now_ts + delay
                bot._abaddon_slash_sync_status = "rate_limited" if kind else "failed"
                bot._abaddon_slash_sync_error = discord_rate_guard.compact_message(raw_error, record=False)[:500]
                bot._abaddon_slash_sync_at = datetime.now().isoformat()
                print(
                    f"[슬래시 명령어 동기화 지연] {bot._abaddon_slash_sync_error} · "
                    f"{delay}초 후 재시도",
                    flush=True,
                )

    if not bot_presence.is_running():
        bot_presence.start()


@tasks.loop(seconds=30)
async def bot_presence():
    registered = len(user_data)
    guild_count = len(bot.guilds)
    member_count = sum(g.member_count or 0 for g in bot.guilds)
    # V7.0: 길드별 실전 월드보스 상태를 기준으로 활동 상태를 표시합니다.
    # 구형 전역 world_boss는 데이터 마이그레이션 전용이며 Presence에는 사용하지 않습니다.
    v700_root = world_data.get("world_boss_v630", {})
    v700_guilds = v700_root.get("guilds", {}) if isinstance(v700_root, dict) else {}
    active_bosses = []
    if isinstance(v700_guilds, dict):
        for guild_state in v700_guilds.values():
            active = guild_state.get("active") if isinstance(guild_state, dict) else None
            if isinstance(active, dict) and active.get("status") == "active" and active.get("hp", 0) > 0:
                active_bosses.append(active)
    boss = min(
        active_bosses,
        key=lambda row: row.get("hp", 0) / max(1, row.get("max_hp", 1)),
        default=None,
    )
    boss_active = isinstance(boss, dict)
    boss_percent = boss.get("hp", 0) / max(1, boss.get("max_hp", 1)) * 100 if boss_active else 0.0
    market_count = len(world_data.get("market", {}))
    guilds = len(world_data.get("guilds", {}))
    activities = [
        discord.Game("Official ABADDON · !help / !명령어"),
        discord.Game("!대화 | 기억 공방과 오늘의 질문"),
        discord.Game("!던전 약함 | 감염자 사냥"),
        discord.Game("!심층던전 | 100층에 도전"),
        discord.Game("!상점 | 암시장 거래"),
        discord.Game("!오늘의퀴즈 | 지식도 생존력"),
        discord.Game("!출석 | 매일 생존 보급품"),
        discord.Game("!길드 | 함께 살아남아라"),
        discord.Game("!강화정보 | 장비 한계 돌파"),
        discord.Game("!보스도감 | 재앙을 기록하라"),
        discord.Game("!거래소 | 생존자 직거래"),
        discord.Game("장애 문의 DM · jjonga0022"),
        discord.Game("Bug support DM · jjonga0022"),
        discord.Game("!서버설정 | 쉬운 서버 관리"),
        discord.Game("!커뮤니티센터 | 문의·음성·역할"),
        discord.Game("!웹대시보드 | Web Dashboard"),
        discord.Activity(type=discord.ActivityType.watching, name=f"등록 생존자 {registered:,}명"),
        discord.Activity(type=discord.ActivityType.watching, name=f"{guild_count}개 서버 · {member_count:,}명"),
        discord.Activity(type=discord.ActivityType.watching, name=f"생존 길드 {guilds:,}개"),
        discord.Activity(type=discord.ActivityType.watching, name=f"거래소 매물 {market_count:,}개"),
        discord.Activity(type=discord.ActivityType.listening, name="폐허 너머의 구조 신호"),
        discord.Activity(type=discord.ActivityType.listening, name="감염자들의 발소리"),
        discord.Activity(type=discord.ActivityType.competing, name="종말 생존 랭킹"),
    ]
    if boss_active:
        activities.extend([
            discord.Activity(type=discord.ActivityType.competing, name=f"{boss['name']} 토벌"),
            discord.Activity(type=discord.ActivityType.watching, name=f"월드보스 HP {boss_percent:.1f}% · {len(active_bosses)}개 서버"),
            discord.Game("!월드보스공격 | 서버 협동 레이드"),
        ])
    else:
        activities.append(discord.Game("월드보스 처치 완료 · 다음 재앙 대기"))
    # v18.3.4: rotate predictably every 30 seconds so every public status,
    # including the support contact, is guaranteed to appear instead of relying on random choice.
    index = int(getattr(bot, "_abaddon_presence_rotation_index", 0) or 0)
    activity = activities[index % max(1, len(activities))]
    setattr(bot, "_abaddon_presence_rotation_index", index + 1)
    # v19.0.1: keep one authoritative copy of the last non-empty activity.
    # The legacy online guard used to race the 30s rotation and could resend
    # activity=None, making the member-list status text disappear every other tick.
    setattr(bot, "_abaddon_last_presence_activity", activity)
    await bot.change_presence(status=discord.Status.online, activity=activity)
    setattr(bot, "_abaddon_presence_last_sent_monotonic", time.monotonic())


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if bot.user and bot.user.mentioned_in(message):
        handled = False
        dialogue_handler = getattr(bot, "_abaddon_dialogue_mention_handler", None)
        if dialogue_handler is not None:
            try:
                handled = bool(await dialogue_handler(message))
            except Exception as exc:
                print(f"[대화 멘션 처리 실패] {type(exc).__name__}: {exc}", flush=True)
        if not handled:
            await message.channel.send(
                f"{message.author.mention} 🗣️ {random.choice(GREETINGS)}"
            )

    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx, error):
    if ctx.command is not None and hasattr(ctx.command, "on_error"):
        return

    # v10.0.0: the first-language selector intentionally stops the original command.
    # The selector itself has already been sent, so this sentinel must stay silent.
    if isinstance(error, commands.CheckFailure) and str(error) == getattr(bot, "v1000_language_check_sentinel", ""):
        _release_command_lock(ctx)
        return

    if isinstance(error, ConcurrentOperation):
        _release_command_lock(ctx)
        view_factory = getattr(bot, "v711_error_view_factory", None)
        view = view_factory(ctx.author.id, ctx.command) if callable(view_factory) else None
        await ctx.send("🫧 앞선 명령을 안전하게 저장하는 중이에요. 잠깐만 기다렸다가 다시 눌러주세요!", view=view)
        return
    if isinstance(error, commands.CommandNotFound):
        raw = str(getattr(ctx.message, "content", "")).lstrip("!").split(maxsplit=1)[0]
        smart_handler = getattr(bot, "v1852_unknown_command_handler", None)
        if callable(smart_handler):
            try:
                if await smart_handler(ctx, raw):
                    return
            except Exception as exc:
                print(f"[스마트 명령 탐색 실패] {type(exc).__name__}: {exc}", flush=True)
        candidates = sorted({name for name in bot.all_commands if not str(name).startswith("_")})
        matches = difflib.get_close_matches(raw, candidates, n=3, cutoff=0.72) if len(raw) >= 2 else []
        view_factory = getattr(bot, "v711_error_view_factory", None)
        view = view_factory(ctx.author.id, None) if callable(view_factory) else None
        if matches:
            suggestions = " · ".join(f"`!{name}`" for name in matches)
            await ctx.send(
                f"🍃 **`!{raw}`** 명령은 아직 못 찾았어요. 혹시 이 명령인가요? {suggestions}\n"
                "아래 **명령어 찾기** 버튼으로 전체 도감을 열 수도 있어요. 🌱",
                view=view,
            )
        else:
            await ctx.send(
                f"🍃 **`!{raw or '?'}`** 명령은 보이지 않아요. 철자 대신 아래 버튼으로 찾아볼까요? 🫧",
                view=view,
            )
        return
    if isinstance(error, commands.MissingRequiredArgument):
        command = ctx.command
        signature = f"!{command.qualified_name} {command.signature}".strip() if command else "!명령어"
        help_text = str(getattr(command, "help", "") or getattr(command, "description", "") or "필요한 값을 입력하세요.")
        view_factory = getattr(bot, "v711_error_view_factory", None)
        view = view_factory(ctx.author.id, command) if callable(view_factory) else None
        await ctx.send(
            f"📝 **입력값이 하나 빠졌어요!**\n사용법: `{signature}`\n{help_text[:500]}\n"
            "아래 버튼을 누르면 입력창으로 다시 실행할 수 있어요. ✨",
            view=view,
        )
        return
    if isinstance(error, commands.BadArgument):
        command = ctx.command
        signature = f"!{command.qualified_name} {command.signature}".strip() if command else "!명령어"
        view_factory = getattr(bot, "v711_error_view_factory", None)
        view = view_factory(ctx.author.id, command) if callable(view_factory) else None
        await ctx.send(
            f"🫧 입력값 모양이 조금 달라요. 멘션·숫자·이름을 다시 확인해주세요.\n사용법: `{signature}`",
            view=view,
        )
        return
    if isinstance(error, commands.CommandOnCooldown):
        remaining = max(1, int(error.retry_after))
        mins, secs = divmod(remaining, 60)
        await ctx.send(f"⏳ 아직 숨을 고르는 중이에요… **{mins}분 {secs}초** 뒤에 다시 만나요! 🌿")
        return

    original = getattr(error, "original", error)
    incident_id = uuid.uuid4().hex[:8].upper()
    recorder = getattr(bot, "v702_record_command_failure", None)
    if callable(recorder):
        recorder(ctx, original, incident_id, max(0.0, time.monotonic() - getattr(ctx, "_abaddon_started_monotonic", time.monotonic())))
    _release_command_lock(ctx)
    print(
        f"[명령어 오류:{incident_id}] 명령={getattr(ctx.command, 'qualified_name', None)} "
        f"유저={getattr(ctx.author, 'id', None)} 길드={getattr(getattr(ctx, 'guild', None), 'id', None)} "
        f"오류={type(original).__name__}: {original}",
        flush=True,
    )
    traceback.print_exception(type(original), original, original.__traceback__)
    try:
        view_factory = getattr(bot, "v711_error_view_factory", None)
        view = view_factory(ctx.author.id, ctx.command) if callable(view_factory) else None
        await ctx.send(
            "🫧 명령어가 잠깐 길을 잃었어요. 재화가 바뀌었는지 확인한 뒤, 계속되면 관리자에게 사건 번호를 알려주세요.\n"
            f"사건 번호: `{incident_id}` · 명령: `{getattr(ctx.command, 'qualified_name', '알 수 없음')}`",
            view=view,
        )
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as notify_exc:
        print(
            f"[명령어 오류 알림 실패:{incident_id}] channel={getattr(getattr(ctx, 'channel', None), 'id', None)} "
            f"{type(notify_exc).__name__}: {notify_exc}",
            flush=True,
        )


# =========================================================
# 가입 / 기본 정보
# =========================================================
@bot.hybrid_command()
async def 가입(ctx, *, 암호: str = ""):
    user_id = str(ctx.author.id)

    if user_id in user_data:
        await ctx.send("⚠️ 이미 암시장에 가입된 생존자입니다.")
        return

    if str(암호).strip().lower() not in {CORRECT_PASSWORD, "survivor"}:
        await ctx.send(
            "❌ 암호가 틀렸습니다. / Incorrect access word.\n"
            "사용법: `!가입 생존자` · English: `!register survivor`"
        )
        return

    user_data[user_id] = default_user()
    user_data[user_id]["tutorial"]["started"] = True
    registration = user_data[user_id].setdefault("registration", {})
    registration["registered_at"] = datetime.now(timezone.utc).isoformat()
    registration["guild_id"] = str(getattr(ctx.guild, "id", "") or "")
    registration["guild_name"] = str(getattr(ctx.guild, "name", "") or "DM")[:100]
    registration["source"] = "signup_v1821"
    ensure_daily_quest(user_data[user_id])
    save_data()

    await ctx.send(
        f"🎉 **[가입 승인]** {ctx.author.mention}님, 생존자 등록이 완료되었습니다.\n"
        "초기 생존 식량 **1,000개** 지급!\n\n"
        "🌱 **처음 10분은 이것만 하면 됩니다**\n"
        "`1.` `!첫10분` — 초보 동선 한눈에 보기\n"
        "`2.` `!오늘할일` — 지금 받을 보상 확인\n"
        "`3.` `!명령어` — 쉬운 카테고리 메뉴 열기\n\n"
        "막히거나 오류가 나면 `!문의처` 또는 **Discord DM `jjonga0022`** 로 알려주세요."
    )


COMMAND_GUIDE_CATEGORIES = [
    {
        "id": "start",
        "emoji": "🧾",
        "title": "가입 / 정보 / 기본",
        "hint": "처음 시작, 지갑, 랭킹, 상태 확인",
        "commands": [
            "!가입 생존자", "!처음 / !초보", "!게임 / !게임센터", "!튜토리얼", "!정보", "!지갑", "!상태", "!랭킹",
            "!출석", "!출석보상", "!송금 @유저 금액", "!돈주세요", "!훈련", "!휴식",
            "!직업목록", "!직업선택 직업명", "!직업정보 [직업명]", "!직업변경 직업명",
            "!칭호목록", "!칭호 칭호이름"
        ],
    },
    {
        "id": "life",
        "emoji": "🌿",
        "title": "생활 / 인카운트 / 보물",
        "hint": "채집, 낚시, 광산, 땅파기, 감정소",
        "commands": [
            "!알바", "!채집", "!낚시", "!벌목", "!광산", "!생활숙련도",
            "!코인 / !코인탐색", "!돈주세요", "!땅파기 / !굴착 / !삽질",
            "!보물감정 / !보물감정소 / !감정소", "!감정사 / !감정사목록", "!보물함",
            "!인카운트도감 / !조우도감 / !랜덤이벤트도감",
            "!무전 / !무전해독 / !SOS", "!위험구역", "!오늘의 운세 / !오늘의운세", "!랜덤박스 [1~3]"
        ],
    },
    {
        "id": "shop",
        "emoji": "🛒",
        "title": "상점 / 장비 / 제작",
        "hint": "구매, 인벤토리, 강화, 제작",
        "commands": [
            "!상점 [티어]", "!장비목록 [티어]", "!구매 아이템명", "!신규장비 [티어]",
            "!인벤토리", "!강화 아이템명", "!강화정보 아이템명", "!보호강화 아이템명",
            "!강화기록", "!강화연출", "!장비외형 아이템명", "!강화랭킹", "!장비옵션 아이템명", "!옵션재설정 아이템명",
            "!세트효과", "!재료", "!제작목록", "!제작 아이템명",
            "!내구도 [장비명]", "!무기수리 [장비명]", "!개조목록", "!개조부품제작 부품명",
            "!무기개조 장비명 부품명", "!개조해제 장비명 부품명"
        ],
    },
    {
        "id": "battle",
        "emoji": "⚔️",
        "title": "전투 / 보스 / 던전",
        "hint": "괴물, 지역, 레이드, 월드보스",
        "commands": [
            "!괴물목록 [난이도]", "!던전 약함/보통/강함/지옥", "!던전전술 약함/보통/강함/지옥", "!전투 [난이도]", "!전투상태", "!전투포기", "!심층던전 [층]", "!던전기록",
            "!지역목록", "!지역정보 [지역명]", "!지역이동 지역명", "!지역탐색", "!좀비도감 [지역명]",
            "!레이드", "!레이드공격", "!월드보스", "!월드보스공격", "!월드보스기여도",
            "!월드보스보상", "!월드보스목록", "!월드보스도감", "!보스도감", "!보스랭킹", "!PVP @유저"
        ],
    },
    {
        "id": "trade",
        "emoji": "💰",
        "title": "거래 / 암시장 / 금융",
        "hint": "거래소, 판매, 은행, 사채, 암시장",
        "commands": [
            "!거래소", "!거래검색 키워드", "!판매 아이템명 가격", "!구매등록번호 번호", "!판매취소 번호",
            "!경매등록 아이템명 시작가", "!입찰 번호 금액", "!경매마감 번호", "!거래기록",
            "!시세", "!매수 일반 10", "!매도 / !코인판매", "!자산", "!암시장기록",
            "!자원시장", "!자원구매 나무 10", "!자원판매 광석 5", "!기지칩교환 고철 10",
            "!까마귀", "!까마귀구매 번호",
            "!은행", "!입금 금액", "!출금 금액", "!대출 금액", "!상환 금액",
            "!사채", "!사채빌리기 금액", "!사채상환 금액", "!사채추심"
        ],
    },
    {
        "id": "casino",
        "emoji": "🎲",
        "title": "카지노 / 도박",
        "hint": "블랙잭, 룰렛, 탐색 도박",
        "commands": [
            "!카지노", "!카지노칩", "!카지노환전 구매/판매 금액", "!카지노VIP", "!카지노잭팟",
            "!카지노미션", "!카지노미션보상 번호", "!카지노업적 [페이지]", "!카지노상점", "!카지노구매 상품 수량",
            "!카지노기록", "!카지노랭킹", "!카지노딜러", "!카지노시즌랭킹 시즌/전체/오늘 페이지",
            "!블랙잭 금액", "!하이로우 금액", "!슬롯 금액", "!다이스 홀/짝/1~6 금액",
            "!바카라 플레이어/뱅커/타이 금액", "!럭키휠", "!코인플립 앞/뒤 금액", "!올인 앞/뒤",
            "!룰렛 배팅액", "!주파수 배팅액", "!탐색 왼쪽/오른쪽 배팅액", "!도박잔액", "!도박정보",
            "!경마 10000", "!경마장", "!경마전적", "!지뢰찾기 5 100000", "!괴질탈출 배팅액",
            "!비상주파수 배팅액", "!돌연변이경주", "!돌연변이배팅 번호 배팅액",
            "!선물거래 방향 배팅액 [레버리지]", "!괴수투기장 @상대 [배팅액]", "!생존룰렛",
            "!파산신청", "!정부지원금"
        ],
    },
    {
        "id": "story",
        "emoji": "📖",
        "title": "스토리 / 원정 / 유물",
        "hint": "시즌 스토리, 원정, 유물 장착",
        "commands": [
            "!rpg", "!rpg 시작", "!rpg 전투 [난이도]", "!스토리", "!스토리 시작", "!스토리 선택 번호", "!스토리 전투 [난이도]", "!스토리 기록", "!스토리 재시작",
            "!시즌2", "!시즌2 시작", "!시즌2 선택 번호", "!시즌2 기록", "!시즌2 재시작", "!시즌2 장면 [번호]",
            "!시즌2 수집", "!시즌2 계승", "!시즌2 복구", "!시즌3", "!시즌3 시작", "!시즌3 선택 번호",
            "!시즌3 기록", "!시즌3 재시작", "!원정 도움말", "!원정 목록", "!원정 출발 지역명",
            "!원정 행동 공격/기술/방어/집중/응급/도주", "!원정 보급", "!원정 유물", "!원정 장비",
            "!원정 임무 [주간]", "!원정 임무보상 일일/주간 번호", "!원정 복구", "!원정 기록", "!원정 랭킹",
            "!유물", "!유물 장착/해제/강화/분해", "!도감", "!도감 장비/펫/몬스터", "!도감보상"
        ],
    },
    {
        "id": "pet",
        "emoji": "🐾",
        "title": "펫",
        "hint": "펫 상점, 장착, 모험, 진화",
        "commands": [
            "!펫", "!펫상점", "!펫구매 펫이름", "!펫목록", "!펫장착 펫이름",
            "!펫정보 [펫이름]", "!펫훈련", "!펫먹이", "!펫모험", "!펫진화"
        ],
    },
    {
        "id": "guild_party",
        "emoji": "👥",
        "title": "길드 / 파티",
        "hint": "길드 생성, 가입, 파티 사냥",
        "commands": [
            "!길드목록", "!길드생성 길드명", "!길드가입 길드명", "!길드정보", "!길드기부 금액", "!길드강화", "!길드탈퇴",
            "!파티생성", "!파티가입 @리더", "!파티정보", "!파티사냥", "!파티탈퇴"
        ],
    },
    {
        "id": "quest",
        "emoji": "🎯",
        "title": "퀘스트 / 시즌패스 / 업적",
        "hint": "일일, 주간, 시즌보상, 업적",
        "commands": [
            "!일일퀘스트", "!퀘스트보상", "!주간퀘스트", "!주간보상", "!시즌패스", "!시즌보상 레벨", "!업적"
        ],
    },
    {
        "id": "base",
        "emoji": "🏕️",
        "title": "기지 / 치료 / 생존",
        "hint": "고난도 기지 건설·시간형 강화·생산 수확·치료",
        "commands": [
            "!의약품", "!약품구매 붕대 1", "!사용 붕대", "!병원", "!자원",
            "!기지 — 현재 단계·생산량·다음 비용·남은 공사 시간",
            "!기지건설 — Lv.1 야영지 건설",
            "!기지강화 — 자원 지불·시간형 단계 업그레이드·완료 확인",
            "!기지수확 — 최대 24시간 누적 생산물 수확",
            "!기지방어 / !기지방어공격 — 주간 서버 협동 방어전",
            "!날씨 — 서버별 2~5시간 랜덤 주기 날씨와 효과 확인",
            "!위험구역 — 매일 지정되는 고위험·고보상 탐색 지역",
            "!자원시장 / !기지칩교환 — 기지 자원 경제"
        ],
    },
    {
        "id": "talk",
        "emoji": "💬",
        "title": "대화 / 서버 기억",
        "hint": "아바돈 대화, 지식 등록/검색",
        "commands": [
            "!대화", "!아바돈 내용", "!가르치기", "!지식", "!지식 검색 단어", "!오늘의질문",
            "!밸런스게임", "!교감", "!한마디", "!응원 [@유저]", "!지식 검수", "!지식 삭제 기억ID",
            "!지식 자동반응 켜기/끄기"
        ],
    },
    {
        "id": "server",
        "emoji": "🛠️",
        "title": "서버 / 유틸 / 관리자",
        "hint": "서버설정, 실시간피드, 관리자 도구",
        "commands": [
            "!서버설정", "!서버세팅 미리보기/실행/상태/취소", "!퀴즈알림설정", "!퀴즈알림상태", "!퀴즈알림해제",
            "!실시간피드상태", "!실시간피드테스트", "!실시간피드 켜기/끄기", "!실시간공지 내용",
            "!가방조회 @유저", "!식량지급 @유저 금액", "!식량회수 @유저 금액", "!월드보스리셋 보스명", "!월드보스테스트 보스명",
            "!시스템점검", "!오류현황", "!운영통계", "!백업목록", "!백업생성", "!백업검증", "!복구미리보기 [파일명]",
            "!테스트 / !테스트 상세 — 최신 패치 읽기 전용 자체 진단"
        ],
    },
]


GUIDE_FEATURED_COMMANDS = {
    "start": ["!가입 생존자", "!처음 / !초보", "!게임 / !게임센터", "!정보", "!출석", "!튜토리얼"],
    "life": ["!알바", "!채집", "!광산", "!땅파기", "!오늘의 운세", "!보물감정"],
    "shop": ["!장비", "!상점", "!인벤토리", "!장착 아이템명", "!강화 아이템명", "!제작목록"],
    "battle": ["!전투 보통", "!던전 보통", "!지역탐색", "!레이드", "!월드보스", "!월드보스공격"],
    "trade": ["!지갑", "!거래소", "!은행", "!암시장", "!송금 @유저 금액", "!자원시장"],
    "casino": ["!도박정보", "!카지노", "!카지노칩", "!카지노미션", "!경마장", "!도박잔액"],
    "story": ["!스토리", "!시즌2", "!시즌3", "!원정", "!유물", "!오늘의퀴즈"],
    "pet": ["!펫", "!펫상점", "!펫목록", "!펫모험", "!펫진화"],
    "guild_party": ["!길드목록", "!길드정보", "!파티생성", "!파티가입 @리더", "!파티사냥"],
    "quest": ["!일일퀘스트", "!퀘스트보상", "!주간퀘스트", "!시즌패스", "!업적"],
    "base": ["!상태", "!병원", "!기지", "!기지강화", "!기지수확", "!날씨"],
    "talk": ["!대화", "!아바돈 내용", "!오늘의질문", "!응원 @유저", "!지식 검색 단어"],
    "server": ["!서버설정", "!운영도움말", "!퀴즈알림상태", "!암시장알림상태", "!테스트"],
}

BEGINNER_GUIDE_STEPS = [
    ("1", "가입", "`!가입 생존자`", "캐릭터를 만들고 초기 식량 1,000개를 받습니다."),
    ("2", "내 상태 확인", "`!정보` · `!상태`", "레벨·식량·HP·스태미나를 확인합니다."),
    ("3", "직업 선택", "`!직업목록` → `!직업선택 직업명`", "처음에는 설명을 읽고 마음에 드는 직업을 고르면 됩니다."),
    ("4", "매일 보상", "`!출석` · `!일일퀘스트`", "접속할 때마다 먼저 확인하면 성장 속도가 빨라집니다."),
    ("5", "첫 전투", "`!훈련` 또는 `!전투 보통`", "장비가 없어도 가능한 안전한 전투부터 시작합니다."),
]

TODAY_GUIDE_COMMANDS = [
    ("🎁", "출석", "`!출석`", "오늘 출석 보상을 받습니다."),
    ("🎯", "일일 퀘스트", "`!일일퀘스트`", "오늘의 목표와 진행도를 확인합니다."),
    ("📅", "주간 퀘스트", "`!주간퀘스트`", "주간 목표를 놓치지 않았는지 확인합니다."),
    ("🧠", "오늘의 퀴즈", "`!오늘의퀴즈`", "퀴즈 보상과 랭킹에 도전합니다."),
    ("☀️", "오늘의 운세", "`!오늘의`", "오늘 적용되는 행운 효과를 확인합니다."),
    ("🌋", "월드보스", "`!월드보스`", "현재 서버 공동 보스와 미수령 보상을 확인합니다."),
]


def _make_beginner_help_embed():
    embed = discord.Embed(
        title="🌱 ABADDON 처음 시작 가이드",
        description=(
            "명령어를 외우지 않아도 됩니다. 아래 순서대로 한 번씩 실행한 뒤 `!게임`을 열면 "
            "버튼과 드롭다운으로 대부분의 기능을 사용할 수 있습니다."
        ),
        color=discord.Color.green(),
    )
    for number, title, command_text, description in BEGINNER_GUIDE_STEPS:
        embed.add_field(name=f"{number}. {title}", value=f"{command_text}\n{description}", inline=False)
    embed.add_field(
        name="막히면",
        value="`!게임`에서 **처음 시작** 선택 · `!명령어 검색어`로 검색 · `!도움말`로 이 화면 다시 열기",
        inline=False,
    )
    embed.set_footer(text="기존 명령어를 외울 필요 없이 !게임 메뉴를 중심으로 이용할 수 있습니다.")
    return embed


def _make_today_help_embed():
    embed = discord.Embed(
        title="☀️ 오늘 먼저 확인할 것",
        description="매일 전부 할 필요는 없습니다. 보상과 진행도를 놓치기 쉬운 기능만 모았습니다.",
        color=discord.Color.gold(),
    )
    for emoji, title, command_text, description in TODAY_GUIDE_COMMANDS:
        embed.add_field(name=f"{emoji} {title}", value=f"{command_text}\n{description}", inline=True)
    embed.set_footer(text="더 많은 추천은 !게임 → 오늘 추천")
    return embed


def _normalize_help_keyword(text):
    return str(text or "").lower().replace("`", "").replace("!", "").replace("/", "").replace(" ", "")


def _command_chunks(commands_list, max_len=900):
    chunks = []
    current = []
    current_len = 0
    for cmd in commands_list:
        line = f"• `{cmd}`"
        if current and current_len + len(line) + 1 > max_len:
            chunks.append("\n".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def _make_help_embed(category=None, *, full=False):
    color = discord.Color.dark_teal()
    if category is None:
        embed = discord.Embed(
            title="📚 ABADDON 명령어 안내",
            description=(
                "**처음 플레이한다면 아래 `처음 시작` 버튼부터 누르세요.**\n"
                "명령어를 외우기보다 `!게임`의 버튼·드롭다운을 사용하는 것을 권장합니다.\n\n"
                "검색 예시: `!명령어 강화` · `!명령어 월드보스` · `!명령어 길드`"
            ),
            color=color,
        )
        embed.add_field(
            name="🌱 30초 시작",
            value="`!가입 생존자` → `!정보` → `!직업목록` → `!출석` → `!게임`",
            inline=False,
        )
        embed.add_field(
            name="🎮 가장 쉬운 이용법",
            value="`!게임` → **처음 시작** 또는 원하는 카테고리 → 기능 설명 확인 → 실행하기",
            inline=False,
        )
        for cat in COMMAND_GUIDE_CATEGORIES[:25]:
            featured_count = len(GUIDE_FEATURED_COMMANDS.get(cat["id"], []))
            embed.add_field(
                name=f"{cat['emoji']} {cat['title']}",
                value=f"{cat['hint']}\n대표 {featured_count}개 · 전체 {len(cat['commands'])}개",
                inline=True,
            )
        embed.set_footer(text="카테고리를 고르면 대표 명령만 먼저 표시됩니다. 필요할 때 전체 목록을 펼치세요.")
        return embed

    embed = discord.Embed(title=f"{category['emoji']} {category['title']}", description=category['hint'], color=color)
    featured = GUIDE_FEATURED_COMMANDS.get(category["id"], category["commands"][:6])
    embed.add_field(
        name="⭐ 처음엔 이것만",
        value="\n".join(f"• `{cmd}`" for cmd in featured)[:1024],
        inline=False,
    )
    if full:
        for idx, chunk in enumerate(_command_chunks(category['commands']), start=1):
            name = "전체 명령어" if idx == 1 else f"전체 명령어 {idx}"
            embed.add_field(name=name, value=chunk, inline=False)
        embed.set_footer(text="전체 목록 표시 중 · 버튼을 누르면 대표 명령만 다시 볼 수 있습니다.")
    else:
        remaining = max(0, len(category["commands"]) - len(featured))
        embed.add_field(
            name="전체 목록이 필요한가요?",
            value=f"비슷한 기능을 묶어 대표 명령만 표시했습니다. 아래 **전체 목록 보기**를 누르면 나머지 **{remaining}개**도 확인할 수 있습니다.",
            inline=False,
        )
        embed.set_footer(text="검색: !명령어 검색어 · 실행 메뉴: !게임")
    return embed

def _search_commands(query, limit=20):
    token = _normalize_help_keyword(query)
    if not token:
        return []
    results = []
    for cat in COMMAND_GUIDE_CATEGORIES:
        title_key = _normalize_help_keyword(cat['title'] + cat['hint'])
        for cmd in cat['commands']:
            norm = _normalize_help_keyword(cmd)
            score = None
            if norm.startswith(token):
                score = 0
            elif token in norm:
                score = 1
            elif token in title_key:
                score = 2
            if score is not None:
                results.append((score, len(cmd), cat['title'], cmd))
    results.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    seen = set()
    final = []
    for _, _, category_title, cmd in results:
        key = (category_title, cmd)
        if key in seen:
            continue
        seen.add(key)
        final.append((category_title, cmd))
        if len(final) >= limit:
            break
    return final


def _make_search_embed(query, results):
    embed = discord.Embed(title=f"🔎 명령어 검색: {query}", color=discord.Color.blurple())
    if not results:
        embed.description = "일치하는 명령어를 찾지 못했습니다. 드롭다운에서 카테고리를 골라 확인해보세요."
        return embed
    lines = [f"• **{category}** — `{cmd}`" for category, cmd in results]
    description = "\n".join(lines[:15])
    embed.description = description
    if len(lines) > 15:
        embed.add_field(name="추가 결과", value=f"그 외 {len(lines) - 15}개 결과가 더 있습니다. 더 구체적으로 검색해보세요.", inline=False)
    embed.set_footer(text="예: !명령어 감 / !명령어 펫 / !명령어 광 / !명령어 보물")
    return embed


class CommandCategorySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=cat['title'][:100],
                value=cat['id'],
                description=f"대표 {len(GUIDE_FEATURED_COMMANDS.get(cat['id'], []))}개 · 전체 {len(cat['commands'])}개 · {cat['hint']}"[:100],
                emoji=cat['emoji'],
            )
            for cat in COMMAND_GUIDE_CATEGORIES
        ]
        super().__init__(placeholder="하고 싶은 분야를 선택하세요", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected = next((cat for cat in COMMAND_GUIDE_CATEGORIES if cat['id'] == self.values[0]), None)
        if not selected:
            await interaction.response.send_message("카테고리를 찾지 못했습니다.", ephemeral=True)
            return
        view = self.view
        if isinstance(view, CommandHelpView):
            view.category_id = selected['id']
            view.full = False
            view.sync_state()
        await interaction.response.edit_message(embed=_make_help_embed(selected, full=False), view=view)


class CommandSearchModal(discord.ui.Modal, title="명령어 검색"):
    검색어 = discord.ui.TextInput(
        label="무엇을 하고 싶나요?",
        placeholder="예: 장비 강화, 월드보스 보상, 길드 가입",
        min_length=1,
        max_length=40,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        query = str(self.검색어.value).strip()
        results = _search_commands(query)
        await interaction.response.send_message(
            embed=_make_search_embed(query, results),
            ephemeral=True,
        )


class CommandHelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.category_id = None
        self.full = False
        self.add_item(CommandCategorySelect())
        self.sync_state()

    def selected_category(self):
        return next((cat for cat in COMMAND_GUIDE_CATEGORIES if cat['id'] == self.category_id), None)

    def sync_state(self):
        self.full_list.disabled = self.category_id is None
        self.full_list.label = "대표만 보기" if self.full else "전체 목록 보기"
        self.full_list.emoji = "📌" if self.full else "📜"

    @discord.ui.button(label="처음 시작", emoji="🌱", style=discord.ButtonStyle.success, row=1)
    async def beginner_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.category_id = None
        self.full = False
        self.sync_state()
        await interaction.response.edit_message(embed=_make_beginner_help_embed(), view=self)

    @discord.ui.button(label="오늘 할 일", emoji="☀️", style=discord.ButtonStyle.primary, row=1)
    async def today_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.category_id = None
        self.full = False
        self.sync_state()
        await interaction.response.edit_message(embed=_make_today_help_embed(), view=self)

    @discord.ui.button(label="전체 목록 보기", emoji="📜", style=discord.ButtonStyle.secondary, row=1)
    async def full_list(self, interaction: discord.Interaction, button: discord.ui.Button):
        category = self.selected_category()
        if category is None:
            await interaction.response.send_message("먼저 위 드롭다운에서 카테고리를 선택해주세요.", ephemeral=True)
            return
        self.full = not self.full
        self.sync_state()
        await interaction.response.edit_message(embed=_make_help_embed(category, full=self.full), view=self)

    @discord.ui.button(label="검색", emoji="🔎", style=discord.ButtonStyle.secondary, row=1)
    async def search_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CommandSearchModal())

    @discord.ui.button(label="처음 화면", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.category_id = None
        self.full = False
        self.sync_state()
        await interaction.response.edit_message(embed=_make_help_embed(), view=self)


@bot.hybrid_command()
async def 명령어(ctx, *, 검색어: str = None):
    view = CommandHelpView()
    if 검색어:
        await ctx.send(embed=_make_search_embed(검색어, _search_commands(검색어)), view=view)
    else:
        await ctx.send(embed=_make_help_embed(), view=view)


@bot.command(name="처음", aliases=["초보", "초보가이드", "시작가이드"], help="처음 시작하는 생존자를 위한 5단계 가이드를 엽니다.")
async def beginner_guide(ctx):
    await ctx.send(embed=_make_beginner_help_embed(), view=CommandHelpView())

@bot.hybrid_command()
async def 정보(ctx):
    if not await check_registered(ctx):
        return

    u = get_user(ctx.author.id)
    total_power = calculate_user_power(u)
    inv_count = len(u["inventory"])
    active_pet_name, active_pet_record = get_pet_record(u)
    pet = (
        f"{get_pet_display_name(active_pet_name, active_pet_record)} Lv.{active_pet_record['level']}"
        if active_pet_name else "없음"
    )
    job_name = u.get("job") or "미선택"
    job_emoji = JOBS.get(job_name, {}).get("emoji", "👤")
    refresh_vitals(u)
    refresh_conditions(u, get_max_hp)
    max_hp = get_max_hp(u)
    max_stamina = get_max_stamina(u)
    save_data()

    await ctx.send(
        f"📊 **[{ctx.author.name} | {u['title']}]**\n"
        f"{job_emoji} 직업: **{job_name}**\n"
        f"🔹 레벨: **Lv.{u['level']}**\n"
        f"❤️ HP: **{u['hp']} / {max_hp}**\n"
        f"⚡ 스태미나: **{u['stamina']} / {max_stamina}**\n"
        f"🦠 감염도: **{u['infection']}%**\n"
        f"📌 상태: **{condition_text(u)}**\n"
        f"⚔️ 종합 전투력: **{total_power}**\n"
        f"🥫 식량: **{u['balance']:,}개**\n"
        f"🎒 장비 수: **{inv_count}개**\n"
        f"🐾 펫: **{pet}**\n"
        f"🏆 던전 승리: **{u['stats']['dungeon_wins']}회**"
    )


@bot.hybrid_command()
async def 지갑(ctx):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    debt = " 🚨 식량 빚 상태" if u["balance"] < 0 else ""
    await ctx.send(f"🥫 보유 식량: **{u['balance']:,}개**{debt}")


@bot.hybrid_command()
async def 송금(ctx, 대상: discord.Member, 금액: int):
    if not await check_registered(ctx):
        return

    sender = get_user(ctx.author.id)
    receiver = get_user(대상.id)

    if 대상.bot or 대상.id == ctx.author.id:
        await ctx.send("⚠️ 자기 자신이나 봇에게는 송금할 수 없습니다.")
        return
    if receiver is None:
        await ctx.send("⚠️ 상대방이 가입하지 않았습니다.")
        return
    if 금액 <= 0 or sender["balance"] < 금액:
        await ctx.send("⚠️ 금액이 잘못됐거나 잔액이 부족합니다.")
        return
    if sender["balance"] < 0:
        await ctx.send("⚠️ 빚이 있는 상태에서는 송금할 수 없습니다.")
        return

    sender["balance"] -= 금액
    receiver["balance"] += 금액
    save_data()

    await ctx.send(
        f"🤝 {ctx.author.mention} → {대상.mention}\n"
        f"생존 식량 **{금액:,}개** 송금 완료."
    )


# =========================================================
# 출석 / 구걸 / 훈련
# =========================================================
@bot.hybrid_command()
async def 출석(ctx):
    if not await check_registered(ctx):
        return

    u = get_user(ctx.author.id)
    now = datetime.now(timezone.utc).astimezone(KST)
    today = now.strftime("%Y-%m-%d")

    if u["last_attendance"] == today:
        await ctx.send("⚠️ 오늘은 이미 출석했습니다.")
        return

    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    if u["last_attendance"] == yesterday:
        u["attendance_streak"] += 1
    else:
        u["attendance_streak"] = 1

    streak_bonus = min(5000, u["attendance_streak"] * 150)
    bonus = 500 + u["level"] * 100 + streak_bonus
    milestone_bonus = 0
    milestone_text = ""
    if u["attendance_streak"] % 30 == 0:
        milestone_bonus = 15000
        add_season_points(u, 150)
        milestone_text = "\n🏆 **30일 연속 출석 보너스!** 식량 +15,000 / 시즌 +150P"
    elif u["attendance_streak"] % 14 == 0:
        milestone_bonus = 7000
        add_season_points(u, 70)
        milestone_text = "\n🎁 **14일 연속 출석 보너스!** 식량 +7,000 / 시즌 +70P"
    elif u["attendance_streak"] % 7 == 0:
        milestone_bonus = 3000
        add_season_points(u, 35)
        milestone_text = "\n✨ **7일 연속 출석 보너스!** 식량 +3,000 / 시즌 +35P"

    total_bonus = bonus + milestone_bonus
    u["last_attendance"] = today
    u["balance"] += total_bonus
    u["stats"]["earned"] += total_bonus
    add_season_points(u, 10)
    save_data()

    await ctx.send(
        f"📅 **[출석 완료]** {u['attendance_streak']}일 연속 출석!\n"
        f"오늘 지급 합계: **{total_bonus:,}개**\n"
        f"현재 잔액: **{u['balance']:,}개**" + milestone_text
    )


@bot.hybrid_command()
async def 출석보상(ctx):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    streak = u.get("attendance_streak", 0)
    next_bonus = min(5000, (streak + 1) * 150)
    await ctx.send(
        f"🎁 **[연속 출석 보상]**\n"
        f"현재 연속 출석: **{streak}일**\n"
        f"다음 출석 연속 보너스: **{next_bonus:,}개**\n"
        "7일·14일·30일째에는 시즌패스 포인트도 함께 쌓입니다."
    )

SUPPORT_DAILY_LIMIT = 50
SUPPORT_COOLDOWN_SECONDS = 60


def _support_kst_date():
    return (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d")


def _ensure_support_profile(user):
    profile = user.setdefault("support_v632", {})
    if not isinstance(profile, dict):
        profile = {}
        user["support_v632"] = profile
    profile.setdefault("date", _support_kst_date())
    profile.setdefault("attempts", 0)
    profile.setdefault("total_attempts", 0)
    if profile.get("date") != _support_kst_date():
        profile["date"] = _support_kst_date()
        profile["attempts"] = 0
    return profile


@bot.hybrid_command()
@commands.cooldown(1, SUPPORT_COOLDOWN_SECONDS, commands.BucketType.user)
async def 돈주세요(ctx):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    profile = _ensure_support_profile(u)
    if int(profile.get("attempts", 0)) >= SUPPORT_DAILY_LIMIT:
        if ctx.command:
            ctx.command.reset_cooldown(ctx)
        await ctx.send(f"🛑 오늘의 긴급 지원 **{SUPPORT_DAILY_LIMIT}회**를 모두 사용했습니다. 자정(KST)에 초기화됩니다.")
        return
    profile["attempts"] = int(profile.get("attempts", 0)) + 1
    profile["total_attempts"] = int(profile.get("total_attempts", 0)) + 1
    remaining = SUPPORT_DAILY_LIMIT - int(profile["attempts"])
    before = int(u.get("balance", 0))
    visual_send = getattr(bot, "v632_send_visual", None)
    visual_edit = getattr(bot, "v632_edit_visual", None)
    visual_tip = getattr(bot, "v632_tip", lambda _k: "대부분은 일반 지원이며 가끔 특별 교섭이 발생합니다.")

    request_embed = discord.Embed(title="🎁 긴급 지원 요청 접수", description="보급망에서 사용 가능한 지원 기록을 확인하고 있습니다...", color=discord.Color.blurple())
    request_embed.add_field(name="📅 오늘 남은 지원", value=f"**{remaining}회**", inline=True)
    request_embed.add_field(name="⏳ 쿨타임", value="**1분**", inline=True)
    request_embed.add_field(name="💡 TIP", value=visual_tip("support"), inline=False)
    message = await visual_send(ctx, request_embed, "activities/support/encounter") if visual_send else await ctx.send(embed=request_embed)
    await asyncio.sleep(0.65)

    roll = random.random()
    eligible_negotiation = False
    if roll < 0.12:
        loss = min(max(0, before), random.randint(120, 900))
        u["balance"] = before - loss
        outcome, delta = "failure", -loss
        title = "💸 가짜 지원 상인에게 당했습니다"
        description = random.choice(["상자가 비어 있었습니다. 운송 보증금만 사라졌습니다.", "상인이 연막탄을 터뜨리고 수수료를 챙겨 달아났습니다.", "위조된 보급 증서였습니다. 확인 비용을 지불했습니다."])
        color, asset_kind, situation = discord.Color.red(), "failure", "사기 거래"
    elif roll < 0.22:
        outcome, delta = "empty", 0
        title, description = "📭 버려진 배급소", "지원 기록은 남아 있었지만 배급소에는 쓸 만한 물자가 없었습니다."
        color, asset_kind, situation = discord.Color.dark_grey(), "failure", "빈 배급소"
    else:
        reward = random.randint(300, 8_000)
        u["balance"] = before + reward
        u.setdefault("stats", {}).setdefault("earned", 0)
        u["stats"]["earned"] += reward
        outcome = "jackpot" if reward >= 7_000 else "success"
        delta = reward
        title = "💎 특별 지원 물자 확보" if outcome == "jackpot" else "🎁 긴급 지원금 수령"
        description = random.choice(["보급 담당자가 활동 기록을 확인하고 식량 묶음을 전달했습니다.", "구호 신호를 확인한 상단이 식량 묶음을 전달했습니다.", "익명의 후원자가 폐허 중계소에 생존 자금을 남겼습니다."])
        color = discord.Color.gold() if outcome == "jackpot" else discord.Color.green()
        asset_kind = "rare" if outcome == "jackpot" else "success"
        situation = "특별 지원 물자" if outcome == "jackpot" else "일반 지원"
        eligible_negotiation = True

    save_data()
    final = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now())
    final.set_author(name=ctx.author.display_name, icon_url=str(ctx.author.display_avatar.url))
    final.add_field(name="💰 이번 결과" if delta >= 0 else "💸 이번 손실", value=f"**{delta:+,} 식량**", inline=True)
    final.add_field(name="💳 현재 잔액", value=f"**{int(u['balance']):,} 식량**", inline=True)
    final.add_field(name="📅 오늘 남은 지원", value=f"**{remaining}회**", inline=True)
    final.add_field(name="⏳ 다음 요청", value="**1분 후**", inline=True)
    final.add_field(name="🎬 상황", value=situation, inline=True)
    final.add_field(name="💡 TIP", value=visual_tip("support"), inline=False)
    final.set_footer(text="ABADDON 긴급 지원 · 하루 50회 · 특별 교섭은 정상 지원 뒤 랜덤 등장")

    # v16.2.1: replace the text-heavy/broken image family with a Korean-safe
    # dynamic information card. If rendering or attachment editing fails, the
    # existing embed + activity artwork path remains as the safe fallback.
    rendered_support = False
    support_renderer = getattr(bot, "v1621_render_support_card", None)
    if support_renderer is not None:
        try:
            card = support_renderer(
                ctx.author.display_name,
                title,
                description,
                int(delta),
                int(u["balance"]),
                int(remaining),
                situation,
                visual_tip("support"),
            )
            support_file = discord.File(card, filename="abaddon_support_result_v1621.png")
            image_embed = discord.Embed(color=color, timestamp=datetime.now())
            image_embed.set_image(url="attachment://abaddon_support_result_v1621.png")
            await message.edit(content=None, embed=image_embed, attachments=[support_file])
            rendered_support = True
        except (TypeError, discord.Forbidden, discord.HTTPException, AttributeError, OSError, ValueError):
            rendered_support = False
    if not rendered_support:
        if visual_edit:
            await visual_edit(message, final, f"activities/support/{asset_kind}")
        else:
            try: await message.edit(embed=final, content=None)
            except (discord.Forbidden, discord.HTTPException, AttributeError): await ctx.send(embed=final)
    for emoji in {"failure": ("💸", "❌"), "empty": ("📭", "🫥"), "success": ("🎁", "✅"), "jackpot": ("💎", "🎊")}[outcome]:
        try: await message.add_reaction(emoji)
        except (discord.Forbidden, discord.HTTPException, AttributeError): break
    if eligible_negotiation:
        maybe_special = getattr(bot, "v632_maybe_special_negotiation", None)
        if maybe_special:
            await maybe_special(ctx, u)


@bot.hybrid_command()
async def 훈련(ctx):
    if not await check_registered(ctx):
        return

    u = get_user(ctx.author.id)
    cost = u["level"] * 900

    if u["balance"] < cost:
        await ctx.send(f"⚠️ 훈련 비용 부족: **{cost:,}개** 필요")
        return

    u["balance"] -= cost
    u["level"] += 1
    save_data()

    await ctx.send(
        f"🎯 **[훈련 성공]** Lv.{u['level']} 달성!\n"
        f"전투력: **{calculate_user_power(u)}**"
    )


# =========================================================
# 상점 / 구매 / 인벤토리
# =========================================================
@bot.hybrid_command()
async def 상점(ctx, 티어: str = None):
    if not await check_registered(ctx):
        return

    tiers = [티어] if 티어 in ITEM_DB else TIER_ORDER
    text = "🛒 **[아포칼립스 암시장]**\n"

    for tier in tiers:
        text += f"\n🔹 **[{tier}]**\n"
        for item, info in ITEM_DB[tier].items():
            text += f"• {item} | {info['price']:,}개 | 전투력 +{info['power']}\n"

    text += "\n구매: `!구매 아이템명`"
    await send_pages(ctx.channel, text)


@bot.hybrid_command()
async def 장비목록(ctx, 티어: str = None):
    if not await check_registered(ctx):
        return

    tiers = [티어] if 티어 in ITEM_DB else TIER_ORDER
    text = "📋 **[장비 전체 목록]**\n"

    for tier in tiers:
        text += f"\n**[{tier}]**\n"
        for item, info in ITEM_DB[tier].items():
            text += f"• **{item}**: {info['desc']} / +{info['power']}\n"

    await send_pages(ctx.channel, text)


@bot.hybrid_command()
async def 구매(ctx, *, 아이템이름: str):
    if not await check_registered(ctx):
        return

    u = get_user(ctx.author.id)
    tier, item = find_item(아이템이름)

    if not item:
        await ctx.send("⚠️ 존재하지 않는 장비입니다.")
        return
    if 아이템이름 in u["inventory"]:
        await ctx.send("⚠️ 이미 보유한 장비입니다.")
        return
    if u["balance"] < item["price"]:
        await ctx.send(f"⚠️ 식량 부족: **{item['price']:,}개** 필요")
        return

    u["balance"] -= item["price"]
    u["inventory"].append(아이템이름)
    u["enhancements"].setdefault(아이템이름, 0)
    u["stats"]["items_bought"] += 1
    progress_quest(u, "아이템 구매")
    unlocked = check_achievements(u)
    save_data()

    msg = (
        f"🛍️ **[구매 성공]** {아이템이름} 획득!\n"
        f"티어: **{tier}** / 기본 전투력 +{item['power']}"
    )
    if unlocked:
        msg += "\n🏆 업적 달성: " + ", ".join(x[0] for x in unlocked)
    await ctx.send(msg)
    visual = getattr(bot, "v633_send_equipment_visual", None)
    if visual:
        await visual(
            ctx,
            item_name=아이템이름,
            tier=tier or "일반",
            slot=get_item_slot(아이템이름),
            level=0,
            mode="acquire",
            description=str(item.get("desc", "")),
        )


@bot.hybrid_command()
async def 인벤토리(ctx):
    if not await check_registered(ctx):
        return

    u = get_user(ctx.author.id)
    equipped_names = {x for x in u.get("equipment", {}).values() if x}
    text = f"🎒 **[{ctx.author.name}님의 인벤토리]**\n"

    if not u["inventory"]:
        text += "보유 장비 없음\n"
    else:
        for item_name in u["inventory"]:
            tier, info = find_item(item_name)
            enhance = u["enhancements"].get(item_name, 0)
            slot = get_item_slot(item_name)
            mark = "✅ 장착" if item_name in equipped_names else "보관"
            text += (
                f"• {TIER_EMOJI.get(tier, '⚪')} [{tier}] {item_name} +{enhance} "
                f"| {slot} | {mark}\n"
            )

    text += (
        f"\n🥫 식량: **{u['balance']:,}개**"
        f"\n🧰 재료 종류: **{sum(1 for v in u.get('materials', {}).values() if v > 0)}종**"
        "\n사용: `!장착 아이템명` / `!버리기 아이템명`"
    )
    await send_pages(ctx.channel, text)


@bot.hybrid_command()
async def 장비(ctx):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    totals = equipment_totals(u)
    lines = ["⚔️ **[장비 현황]**"]
    for slot in EQUIPMENT_SLOTS:
        item = u["equipment"].get(slot)
        if item:
            tier, _ = find_item(item)
            enhance = u["enhancements"].get(item, 0)
            lines.append(f"• {slot}: {TIER_EMOJI.get(tier, '⚪')} **{item} +{enhance}**")
        else:
            lines.append(f"• {slot}: 비어 있음")
    lines.append(
        "\n📊 **장비 능력치**\n"
        f"공격력 +{totals['공격력']} | 방어력 +{totals['방어력']}\n"
        f"치명타 +{totals['치명타']}% | 회피 +{totals['회피']}%\n"
        f"감염저항 +{totals['감염저항']}% | 행운 +{totals['행운']}"
    )
    await ctx.send("\n".join(lines))
    visual = getattr(bot, "v633_send_equipment_visual", None)
    if visual:
        equipped = [item for item in u.get("equipment", {}).values() if item]
        if equipped:
            strongest = max(equipped, key=lambda name: int(u.get("enhancements", {}).get(name, 0)))
            tier, info = find_item(strongest)
            await visual(
                ctx,
                item_name=strongest,
                tier=tier or "일반",
                slot=get_item_slot(strongest),
                level=int(u.get("enhancements", {}).get(strongest, 0)),
                mode="status",
                description=str((info or {}).get("desc", "")),
            )


@bot.hybrid_command()
async def 장착(ctx, *, 아이템이름: str):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    if 아이템이름 not in u["inventory"]:
        await ctx.send("⚠️ 해당 장비를 보유하고 있지 않습니다.")
        return
    slot = get_item_slot(아이템이름)
    previous = u["equipment"].get(slot)
    u["equipment"][slot] = 아이템이름
    save_data()
    msg = f"✅ **{아이템이름}**을(를) **{slot}** 슬롯에 장착했습니다."
    if previous and previous != 아이템이름:
        msg += f"\n기존 장비 **{previous}**은 인벤토리로 돌아갔습니다."
    await ctx.send(msg)
    visual = getattr(bot, "v633_send_equipment_visual", None)
    if visual:
        tier, info = find_item(아이템이름)
        await visual(
            ctx,
            item_name=아이템이름,
            tier=tier or "일반",
            slot=slot,
            level=int(u.get("enhancements", {}).get(아이템이름, 0)),
            mode="equip",
            description=str((info or {}).get("desc", "")),
        )


@bot.hybrid_command()
async def 해제(ctx, *, 슬롯또는아이템: str):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    target_slot = None
    if 슬롯또는아이템 in EQUIPMENT_SLOTS:
        target_slot = 슬롯또는아이템
    else:
        for slot, item in u["equipment"].items():
            if item == 슬롯또는아이템:
                target_slot = slot
                break
    if not target_slot or not u["equipment"].get(target_slot):
        await ctx.send("⚠️ 해당 슬롯이나 장착 중인 아이템을 찾지 못했습니다.")
        return
    item = u["equipment"][target_slot]
    u["equipment"][target_slot] = None
    save_data()
    await ctx.send(f"📦 **{item}** 장착을 해제했습니다.")


@bot.hybrid_command()
async def 버리기(ctx, *, 아이템이름: str):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    if 아이템이름 not in u["inventory"]:
        await ctx.send("⚠️ 보유하지 않은 아이템입니다.")
        return
    if 아이템이름 in u.get("equipment", {}).values():
        await ctx.send("⚠️ 장착 중인 장비는 버릴 수 없습니다. 먼저 `!해제`하세요.")
        return
    tier, info = find_item(아이템이름)
    scrap = max(1, info["price"] // 20) if info else 1
    u["inventory"].remove(아이템이름)
    u["enhancements"].pop(아이템이름, None)
    u["balance"] += scrap
    save_data()
    await ctx.send(f"🗑️ **{아이템이름}**을 버리고 식량 **{scrap:,}개**를 회수했습니다.")


@bot.hybrid_command()
async def 감정(ctx, *, 아이템이름: str):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    if 아이템이름 not in u["inventory"]:
        await ctx.send("⚠️ 보유하지 않은 아이템입니다.")
        return
    tier, info = find_item(아이템이름)
    stats = get_item_stats(아이템이름)
    if 아이템이름 not in u["identified_items"]:
        cost = max(100, info["price"] // 25)
        if u["balance"] < cost:
            await ctx.send(f"⚠️ 감정 비용 **{cost:,}개**가 필요합니다.")
            return
        u["balance"] -= cost
        u["identified_items"].append(아이템이름)
        save_data()
    stat_text = ", ".join(f"{k} +{v}{'%' if k in ['치명타','회피','감염저항'] else ''}" for k, v in stats.items() if v)
    await ctx.send(
        f"🔍 **[장비 감정서]**\n"
        f"{TIER_EMOJI.get(tier, '⚪')} **[{tier}] {아이템이름}**\n"
        f"슬롯: **{get_item_slot(아이템이름)}**\n"
        f"설명: {info['desc']}\n"
        f"능력치: {stat_text or '특수 능력치 없음'}"
    )
    visual = getattr(bot, "v633_send_equipment_visual", None)
    if visual:
        await visual(
            ctx,
            item_name=아이템이름,
            tier=tier or "일반",
            slot=get_item_slot(아이템이름),
            level=int(u.get("enhancements", {}).get(아이템이름, 0)),
            mode="identify",
            description=str(info.get("desc", "")),
            stats_text=stat_text,
        )


# =========================================================
# 강화 시스템
# =========================================================
@bot.hybrid_command()
async def 강화(ctx, *, 아이템이름: str):
    if not await check_registered(ctx):
        return

    u = get_user(ctx.author.id)

    if 아이템이름 not in u["inventory"]:
        await ctx.send("⚠️ 해당 장비를 보유하고 있지 않습니다.")
        return

    current = u["enhancements"].get(아이템이름, 0)
    if current >= 20:
        await ctx.send("⚠️ 이미 최대 강화 수치 +20입니다.")
        return

    _, info = find_item(아이템이름)
    cost = int(info["price"] * (0.12 + current * 0.04))
    success_rate = max(15, 90 - current * 4)

    if u["balance"] < cost:
        await ctx.send(f"⚠️ 강화 비용 **{cost:,}개**가 필요합니다.")
        return

    u["balance"] -= cost
    roll = random.randint(1, 100)

    if roll <= success_rate:
        u["enhancements"][아이템이름] = current + 1
        u["stats"]["enhance_success"] += 1
        progress_quest(u, "강화 성공")
        result = f"✅ 강화 성공! **{아이템이름} +{current + 1}**"
    else:
        # +10 이상부터 낮은 확률로 1단계 하락
        if current >= 10 and random.random() < 0.35:
            u["enhancements"][아이템이름] = current - 1
            result = f"💥 강화 실패! 장비가 **+{current - 1}**로 하락했습니다."
        else:
            result = "❌ 강화 실패! 강화 수치는 유지됩니다."

    unlocked = check_achievements(u)
    save_data()

    msg = (
        f"🔨 **[강화 결과]**\n{result}\n"
        f"비용: {cost:,}개 / 성공 확률: {success_rate}%"
    )
    if unlocked:
        msg += "\n🏆 업적 달성: " + ", ".join(x[0] for x in unlocked)
    await ctx.send(msg)


# =========================================================
# 재료 / 제작
# =========================================================
@bot.hybrid_command()
async def 재료(ctx):
    if not await check_registered(ctx):
        return

    u = get_user(ctx.author.id)
    lines = [
        f"• {m}: {u['materials'].get(m, 0)}개"
        for m in MATERIALS
    ]
    await ctx.send("🧰 **[보유 재료]**\n" + "\n".join(lines))


@bot.hybrid_command()
async def 제작목록(ctx):
    if not await check_registered(ctx):
        return

    text = "🛠️ **[제작 레시피]**\n"
    for item, recipe in CRAFT_RECIPES.items():
        materials = ", ".join(f"{k} {v}개" for k, v in recipe.items())
        text += f"• **{item}**: {materials}\n"

    await send_pages(ctx.channel, text)


@bot.hybrid_command()
async def 제작(ctx, *, 아이템이름: str):
    if not await check_registered(ctx):
        return

    u = get_user(ctx.author.id)
    recipe = CRAFT_RECIPES.get(아이템이름)

    if not recipe:
        await ctx.send("⚠️ 제작 가능한 아이템이 아닙니다.")
        return
    if 아이템이름 in u["inventory"]:
        await ctx.send("⚠️ 이미 보유한 장비입니다.")
        return

    missing = []
    for material, amount in recipe.items():
        owned = u["materials"].get(material, 0)
        if owned < amount:
            missing.append(f"{material} {amount - owned}개")

    if missing:
        await ctx.send("⚠️ 부족한 재료: " + ", ".join(missing))
        return

    suspense = await ctx.send(
        f"🛠️ **{아이템이름} 제작 시작...**\n"
        "▰▰▱▱▱ 재료를 분해하고 작업대를 예열합니다."
    )
    await asyncio.sleep(0.6)
    try:
        await suspense.edit(
            content=(
                f"⚙️ **{아이템이름} 조립 중...**\n"
                "▰▰▰▰▱ 결합부와 에너지 흐름을 점검합니다."
            )
        )
    except (discord.Forbidden, discord.HTTPException, AttributeError):
        pass
    await asyncio.sleep(0.6)

    fail_chance = craft_failure_chance(recipe)
    if random.random() < fail_chance:
        before_balance = int(u.get("balance", 0))
        loss = craft_failure_cost(before_balance, recipe)
        u["balance"] = max(0, before_balance - loss)
        crafting = ensure_crafting_v624(u)
        crafting["failures"] = int(crafting.get("failures", 0)) + 1
        crafting["total_failure_cost"] = int(crafting.get("total_failure_cost", 0)) + loss
        crafting["last_failure_item"] = 아이템이름
        save_data()

        embed = discord.Embed(
            title="💥 제작 실패",
            description=random.choice([
                "접합부가 틀어지며 작업대의 전원 계통이 타버렸습니다.",
                "설계 수치가 어긋나 부품을 다시 분해해야 합니다.",
                "에너지 흐름이 역류해 긴급 정지 장치가 작동했습니다.",
                "마지막 고정핀에서 균열이 발견되어 제작을 중단했습니다.",
            ]),
            color=discord.Color.red(),
        )
        embed.add_field(name="🛠️ 제작 대상", value=f"**{아이템이름}**", inline=True)
        embed.add_field(
            name="💸 작업대 수리비",
            value=f"**-{loss:,} 식량**" if loss else "**0 식량 · 잔액 보호**",
            inline=True,
        )
        embed.add_field(name="💳 현재 잔액", value=f"**{int(u.get('balance', 0)):,} 식량**", inline=True)
        embed.add_field(name="🎲 실패 확률", value=f"**{fail_chance * 100:.1f}%**", inline=True)
        embed.add_field(name="📦 제작 재료", value="**보존됨**", inline=True)
        embed.add_field(
            name="📉 누적 수리비",
            value=f"**{int(crafting.get('total_failure_cost', 0)):,} 식량**",
            inline=True,
        )
        embed.set_footer(text="실패 시 재료는 사라지지 않고 작업대 수리비만 무작위로 차감됩니다")
        visual = getattr(bot, "v633_edit_craft_visual", None)
        tier, _info = find_item(아이템이름)
        if visual:
            await visual(
                suspense,
                embed,
                item_name=아이템이름,
                tier=tier or "일반",
                slot=get_item_slot(아이템이름),
                success=False,
            )
        else:
            try:
                await suspense.edit(content=None, embed=embed)
            except (discord.Forbidden, discord.HTTPException, AttributeError):
                pass
        return

    for material, amount in recipe.items():
        u["materials"][material] -= amount

    u["inventory"].append(아이템이름)
    u["enhancements"][아이템이름] = 0
    u["stats"]["craft_count"] += 1
    progress_quest(u, "제작 성공")
    unlocked = check_achievements(u)
    save_data()

    embed = discord.Embed(
        title="✅ 제작 성공",
        description=f"작업대에서 **{아이템이름}** 제작을 완료했습니다.",
        color=discord.Color.green(),
    )
    embed.add_field(name="🛠️ 완성 장비", value=f"**{아이템이름}**", inline=True)
    embed.add_field(
        name="📦 사용 재료",
        value=" · ".join(f"{name} {amount}개" for name, amount in recipe.items()),
        inline=False,
    )
    embed.add_field(name="💳 현재 잔액", value=f"**{int(u.get('balance', 0)):,} 식량**", inline=True)
    embed.add_field(name="📊 제작 성공 누계", value=f"**{int(u['stats'].get('craft_count', 0))}회**", inline=True)
    if unlocked:
        embed.add_field(name="🏆 업적 달성", value=", ".join(x[0] for x in unlocked), inline=False)
    embed.set_footer(text="ABADDON 제작 기록 · 결과를 항목별 임베드로 표시")
    visual = getattr(bot, "v633_edit_craft_visual", None)
    tier, _info = find_item(아이템이름)
    if visual:
        await visual(
            suspense,
            embed,
            item_name=아이템이름,
            tier=tier or "일반",
            slot=get_item_slot(아이템이름),
            success=True,
        )
    else:
        try:
            await suspense.edit(content=None, embed=embed)
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            pass


# =========================================================
# 펫 동료 시스템 V3.5
# =========================================================
async def _pet_shop_message(ctx):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    owned = ensure_pet_collection(u)
    lines = ["🐾 **[펫 동료 상점]**"]
    for name, info in PET_DB.items():
        marker = "✅ 보유" if name in owned else f"🥫 {info['price']:,}개"
        lines.append(
            f"{info['emoji']} **{name}** · {info['rarity']} · {marker}\n"
            f"└ 기본 전투력 +{info['power']} · **{info['skill']}**: {info['skill_desc']}"
        )
    lines.append("\n구매: `!펫구매 펫이름` 또는 `/펫 구매`")
    await send_pages(ctx.channel, "\n".join(lines))
    visual_shop = getattr(bot, "v634_send_pet_shop", None)
    if visual_shop:
        await visual_shop(ctx)


async def _pet_buy(ctx, pet_name):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    pet_name = (pet_name or "").strip()
    info = PET_DB.get(pet_name)
    if not info:
        await ctx.send("⚠️ 존재하지 않는 펫입니다. `!펫상점` 또는 `/펫 상점`을 확인하세요.")
        return

    collection = ensure_pet_collection(u)
    if pet_name in collection:
        await ctx.send(f"⚠️ **{pet_name}**은(는) 이미 보유 중입니다. `!펫장착 {pet_name}`으로 동행시킬 수 있습니다.")
        return
    if u["balance"] < info["price"]:
        await ctx.send(f"⚠️ 식량 **{info['price']:,}개**가 필요합니다. 현재 **{u['balance']:,}개**")
        return

    u["balance"] -= info["price"]
    collection[pet_name] = _new_pet_record()
    if not u.get("pet"):
        u["pet"] = pet_name
        u["pet_level"] = 1
        equipped_text = "\n⭐ 첫 펫이라 자동으로 장착되었습니다."
    else:
        equipped_text = f"\n`!펫장착 {pet_name}` 또는 `/펫 장착`으로 교체할 수 있습니다."
    codex = u.setdefault("collection_codex", {}).setdefault("pets", [])
    if pet_name not in codex:
        codex.append(pet_name)
    save_data()
    await ctx.send(
        f"{info['emoji']} **{pet_name}**이(가) 새로운 동료가 되었습니다!\n"
        f"고유 능력: **{info['skill']}** — {info['skill_desc']}"
        f"{equipped_text}"
    )
    visual = getattr(bot, "v634_send_pet_visual", None)
    if visual:
        await visual(ctx, pet_name=pet_name, record=collection[pet_name], mode="buy")


async def _pet_list_message(ctx):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    collection = ensure_pet_collection(u)
    if not collection:
        await ctx.send("🐾 아직 보유한 펫이 없습니다. `!펫상점` 또는 `/펫 상점`을 확인하세요.")
        return

    owned_count = sum(1 for name in collection if name in PET_DB)
    lines = [f"🐾 **[{ctx.author.name}님의 펫 목록]** · {owned_count}/{len(PET_DB)}"]
    for name in PET_DB:
        if name not in collection:
            continue
        record = collection[name]
        info = PET_DB[name]
        active = "⭐" if u.get("pet") == name else "▫️"
        display = get_pet_display_name(name, record)
        lines.append(
            f"{active} {info['emoji']} **{display}** · Lv.{record['level']} · 친밀도 {record['friendship']} "
            f"· 전투력 +{get_pet_power(u, name)}"
        )
    lines.append("\n⭐ = 현재 동행 중 · 장착: `!펫장착 펫이름` 또는 `/펫 장착`")
    await send_pages(ctx.channel, "\n".join(lines))
    active_name = u.get("pet")
    visual = getattr(bot, "v634_send_pet_visual", None)
    if visual and active_name in collection and active_name in PET_DB:
        await visual(ctx, pet_name=active_name, record=collection[active_name], mode="list", extra="현재 함께 이동 중인 동료입니다.")


async def _pet_equip(ctx, pet_name):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    pet_name = (pet_name or "").strip()
    collection = ensure_pet_collection(u)
    if pet_name not in collection:
        await ctx.send("⚠️ 보유하지 않은 펫입니다. `!펫목록` 또는 `/펫 목록`을 확인하세요.")
        return
    if pet_name not in PET_DB:
        await ctx.send("⚠️ 현재 버전에서 사용할 수 없는 펫입니다.")
        return
    if u.get("pet") == pet_name:
        await ctx.send(f"🐾 **{pet_name}**은(는) 이미 함께하고 있습니다.")
        return
    u["pet"] = pet_name
    u["pet_level"] = collection[pet_name]["level"]
    save_data()
    await ctx.send(f"⭐ {PET_DB[pet_name]['emoji']} **{get_pet_display_name(pet_name, collection[pet_name])}**을(를) 동행 펫으로 장착했습니다.")
    visual = getattr(bot, "v634_send_pet_visual", None)
    if visual:
        await visual(ctx, pet_name=pet_name, record=collection[pet_name], mode="equip")


async def _pet_info_message(ctx, pet_name=None):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    pet_name = (pet_name or "").strip() or None
    name, record = get_pet_record(u, pet_name)
    if not name:
        if pet_name:
            await ctx.send("⚠️ 보유하지 않은 펫입니다. `!펫목록` 또는 `/펫 목록`을 확인하세요.")
        else:
            await ctx.send("⚠️ 현재 동행 중인 펫이 없습니다. `!펫상점` 또는 `/펫 상점`을 확인하세요.")
        return

    info = PET_DB[name]
    required = pet_exp_required(record["level"]) if record["level"] < PET_MAX_LEVEL else 0
    feed_left = pet_cooldown_remaining(record, "last_feed", PET_FEED_COOLDOWN_MINUTES)
    adventure_left = pet_cooldown_remaining(record, "last_adventure", PET_ADVENTURE_COOLDOWN_MINUTES)
    evolution_text = ["기본", "1차 진화", "최종 진화"][record["evolution"]]
    exp_text = "MAX" if record["level"] >= PET_MAX_LEVEL else f"{record['exp']} / {required}"
    active_text = "⭐ 현재 동행 중" if u.get("pet") == name else "보유 중 · 미장착"

    await ctx.send(
        f"{info['emoji']} **[{get_pet_display_name(name, record)}]** · {info['rarity']}\n"
        f"상태: **{active_text}**\n"
        f"레벨: **Lv.{record['level']} / {PET_MAX_LEVEL}** · 경험치 **{exp_text}**\n"
        f"진화: **{evolution_text}** · 친밀도 **{record['friendship']}**\n"
        f"전투력 보너스: **+{get_pet_power(u, name)}**\n"
        f"고유 능력: **{info['skill']}** — {info['skill_desc']}\n"
        f"🍖 먹이: **{format_seconds(feed_left)}** · 🧭 모험: **{format_seconds(adventure_left)}**\n"
        f"설명: {info['desc']}"
    )
    visual = getattr(bot, "v634_send_pet_visual", None)
    if visual:
        await visual(ctx, pet_name=name, record=record, mode="info", extra=active_text)


async def _pet_train(ctx):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    name, record = get_pet_record(u)
    if not name:
        await ctx.send("⚠️ 먼저 펫을 장착하세요.")
        return
    if record["level"] >= PET_MAX_LEVEL:
        await ctx.send(f"🏆 **{get_pet_display_name(name, record)}**은(는) 이미 최고 레벨입니다.")
        return

    rarity = PET_RARITY_ORDER.get(PET_DB[name]["rarity"], 1)
    cost = 1300 + record["level"] * 1100 + rarity * 400
    if u["balance"] < cost:
        await ctx.send(f"⚠️ 훈련 비용 **식량 {cost:,}개**가 필요합니다. 현재 **{u['balance']:,}개**")
        return

    before_power = get_pet_power(u)
    u["balance"] -= cost
    record["level"] += 1
    record["friendship"] += 2
    u["pet_level"] = record["level"]
    after_power = get_pet_power(u)
    save_data()
    await ctx.send(
        f"🏋️ **[펫 훈련 완료]** {get_pet_display_name(name, record)} Lv.{record['level']} 달성!\n"
        f"전투력 **+{before_power} → +{after_power}** · 친밀도 **+2** · 식량 **-{cost:,}**"
    )
    visual = getattr(bot, "v634_send_pet_visual", None)
    if visual:
        await visual(ctx, pet_name=name, record=record, mode="train", extra=f"훈련으로 전투력이 +{before_power}에서 +{after_power}로 성장했습니다.")


async def _pet_feed(ctx):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    name, record = get_pet_record(u)
    if not name:
        await ctx.send("⚠️ 먼저 펫을 장착하세요.")
        return
    remaining = pet_cooldown_remaining(record, "last_feed", PET_FEED_COOLDOWN_MINUTES)
    if remaining:
        await ctx.send(f"⏳ 다시 먹이를 줄 수 있을 때까지 **{format_seconds(remaining)}** 남았습니다.")
        return

    cost = 450 + record["level"] * 70
    if u["balance"] < cost:
        await ctx.send(f"⚠️ 먹이 비용 **식량 {cost:,}개**가 필요합니다.")
        return

    u["balance"] -= cost
    friendship_gain = random.randint(5, 9)
    exp_gain = random.randint(15, 25)
    record["friendship"] += friendship_gain
    record["last_feed"] = datetime.now().isoformat()
    level_ups = gain_pet_exp(u, exp_gain)
    save_data()
    level_text = f"\n🎉 펫 레벨이 **{level_ups}단계** 올랐습니다!" if level_ups else ""
    await ctx.send(
        f"🍖 **{get_pet_display_name(name, record)}**에게 먹이를 주었습니다.\n"
        f"친밀도 **+{friendship_gain}** · 펫 경험치 **+{exp_gain}** · 식량 **-{cost:,}**"
        f"{level_text}"
    )
    visual = getattr(bot, "v634_send_pet_visual", None)
    if visual:
        await visual(ctx, pet_name=name, record=record, mode="feed", extra=f"간식을 먹고 친밀도가 {friendship_gain} 올랐습니다.")


async def _pet_adventure(ctx):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    name, record = get_pet_record(u)
    if not name:
        await ctx.send("⚠️ 먼저 펫을 장착하세요.")
        return
    remaining = pet_cooldown_remaining(record, "last_adventure", PET_ADVENTURE_COOLDOWN_MINUTES)
    if remaining:
        await ctx.send(f"⏳ 펫이 다시 모험을 떠날 때까지 **{format_seconds(remaining)}** 남았습니다.")
        return

    rarity = PET_RARITY_ORDER.get(PET_DB[name]["rarity"], 1)
    evolution = record["evolution"]
    food = random.randint(250, 650) + rarity * 100 + record["level"] * 15 + evolution * 300
    material_name = random.choice(MATERIALS)
    material_amount = random.randint(1, 2 + max(0, rarity // 3) + evolution)
    exp_gain = random.randint(25, 45) + rarity * 3
    friendship_gain = random.randint(2, 5)

    u["balance"] += food
    u.setdefault("stats", {}).setdefault("earned", 0)
    u["stats"]["earned"] += food
    u.setdefault("materials", {})
    u["materials"][material_name] = u["materials"].get(material_name, 0) + material_amount
    record["friendship"] += friendship_gain
    record["last_adventure"] = datetime.now().isoformat()
    level_ups = gain_pet_exp(u, exp_gain)
    save_data()

    level_text = f"\n🎉 모험 중 펫 레벨이 **{level_ups}단계** 올랐습니다!" if level_ups else ""
    await ctx.send(
        f"🧭 **[펫 모험 귀환]** {get_pet_display_name(name, record)}이(가) 무사히 돌아왔습니다.\n"
        f"🥫 식량 **+{food:,}개** · 🧰 {material_name} **+{material_amount}개**\n"
        f"✨ 펫 경험치 **+{exp_gain}** · 친밀도 **+{friendship_gain}**"
        f"{level_text}"
    )
    visual = getattr(bot, "v634_send_pet_visual", None)
    if visual:
        await visual(ctx, pet_name=name, record=record, mode="adventure", extra=f"식량 {food:,}개와 {material_name} {material_amount}개를 찾아왔습니다.")


async def _pet_evolve(ctx):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    name, record = get_pet_record(u)
    if not name:
        await ctx.send("⚠️ 먼저 펫을 장착하세요.")
        return
    stage = record["evolution"]
    if stage >= PET_MAX_EVOLUTION:
        await ctx.send(f"🌌 **{get_pet_display_name(name, record)}**은(는) 이미 최종 진화를 완료했습니다.")
        return

    requirements = [
        {"level": 10, "friendship": 30, "cost": 20000},
        {"level": 25, "friendship": 100, "cost": 80000},
    ][stage]
    missing = []
    if record["level"] < requirements["level"]:
        missing.append(f"레벨 {requirements['level']}")
    if record["friendship"] < requirements["friendship"]:
        missing.append(f"친밀도 {requirements['friendship']}")
    if u["balance"] < requirements["cost"]:
        missing.append(f"식량 {requirements['cost']:,}개")
    if missing:
        await ctx.send("⚠️ 진화 조건이 부족합니다: **" + " / ".join(missing) + "**")
        return

    before_name = get_pet_display_name(name, record)
    before_power = get_pet_power(u)
    u["balance"] -= requirements["cost"]
    record["evolution"] += 1
    after_name = get_pet_display_name(name, record)
    after_power = get_pet_power(u)
    save_data()
    await ctx.send(
        f"🌌 **[펫 진화 성공]**\n"
        f"{PET_DB[name]['emoji']} **{before_name} → {after_name}**\n"
        f"전투력 **+{before_power} → +{after_power}** · 식량 **-{requirements['cost']:,}개**"
    )
    visual = getattr(bot, "v634_send_pet_visual", None)
    if visual:
        await visual(ctx, pet_name=name, record=record, mode="evolve", extra=f"{before_name}에서 {after_name}(으)로 진화했습니다!")


# 기존 최상위 ! 및 / 명령어 호환 유지
@bot.hybrid_command(description="구매 가능한 펫과 고유 능력을 확인합니다.")
async def 펫상점(ctx):
    await _pet_shop_message(ctx)


@bot.hybrid_command(description="새 펫을 구매해 컬렉션에 추가합니다.")
async def 펫구매(ctx, *, 펫이름: str):
    await _pet_buy(ctx, 펫이름)


@bot.hybrid_command(description="현재 동행 중이거나 보유한 펫의 정보를 확인합니다.")
async def 펫정보(ctx, *, 펫이름: str = None):
    await _pet_info_message(ctx, 펫이름)


@bot.hybrid_command(description="현재 동행 중인 펫을 한 단계 훈련합니다.")
async def 펫훈련(ctx):
    await _pet_train(ctx)


# 새로운 펫 명령어는 !최상위 명령어와 /펫 하위 명령어를 모두 지원합니다.
@bot.command(name="펫목록")
async def pet_list_legacy(ctx):
    await _pet_list_message(ctx)


@bot.command(name="펫장착")
async def pet_equip_legacy(ctx, *, 펫이름: str):
    await _pet_equip(ctx, 펫이름)


@bot.command(name="펫먹이")
async def pet_feed_legacy(ctx):
    await _pet_feed(ctx)


@bot.command(name="펫모험")
async def pet_adventure_legacy(ctx):
    await _pet_adventure(ctx)


@bot.command(name="펫진화")
async def pet_evolve_legacy(ctx):
    await _pet_evolve(ctx)


@bot.hybrid_group(name="펫", fallback="정보", invoke_without_command=True, description="펫 동료를 수집하고 성장시킵니다.")
async def pet_group(ctx, 펫이름: str = None):
    await _pet_info_message(ctx, 펫이름)


@pet_group.command(name="상점", description="구매 가능한 펫과 고유 능력을 확인합니다.")
async def pet_group_shop(ctx):
    await _pet_shop_message(ctx)


@pet_group.command(name="구매", description="새 펫을 구매해 컬렉션에 추가합니다.")
async def pet_group_buy(ctx, 펫이름: str):
    await _pet_buy(ctx, 펫이름)


@pet_group.command(name="목록", description="보유한 모든 펫과 성장 상태를 확인합니다.")
async def pet_group_list(ctx):
    await _pet_list_message(ctx)


@pet_group.command(name="장착", description="보유한 펫을 동행 펫으로 교체합니다.")
async def pet_group_equip(ctx, 펫이름: str):
    await _pet_equip(ctx, 펫이름)


@pet_group.command(name="훈련", description="현재 동행 중인 펫을 한 단계 훈련합니다.")
async def pet_group_train(ctx):
    await _pet_train(ctx)


@pet_group.command(name="먹이", description="펫에게 먹이를 주어 친밀도와 경험치를 올립니다.")
async def pet_group_feed(ctx):
    await _pet_feed(ctx)


@pet_group.command(name="모험", description="펫을 모험에 보내 식량과 재료를 획득합니다.")
async def pet_group_adventure(ctx):
    await _pet_adventure(ctx)


@pet_group.command(name="진화", description="레벨과 친밀도 조건을 충족한 펫을 진화시킵니다.")
async def pet_group_evolve(ctx):
    await _pet_evolve(ctx)


# =========================================================
# 던전 / 괴물 / 드롭 / 크리티컬 / 회피
# =========================================================
@bot.hybrid_command()
async def 괴물목록(ctx, 난이도: str = None):
    난이도 = {"weak":"약함", "easy":"약함", "normal":"보통", "medium":"보통", "hard":"강함", "hell":"지옥"}.get(str(난이도 or "").lower(), 난이도)
    if not await check_registered(ctx):
        return

    difficulties = [난이도] if 난이도 in DUNGEONS else list(DUNGEONS.keys())
    text = "💀 **[괴물 도감]**\n"

    for diff in difficulties:
        d = DUNGEONS[diff]
        text += f"\n🚨 **[{diff}] {d['name']}**\n"
        for monster in d["monsters"]:
            text += f"• {monster['name']} — {monster['desc']}\n"

    await send_pages(ctx.channel, text)


@bot.hybrid_command()
@commands.cooldown(1, 180, commands.BucketType.user)
async def 던전(ctx, 난이도: str = None):
    난이도 = {"weak":"약함", "easy":"약함", "normal":"보통", "medium":"보통", "hard":"강함", "hell":"지옥"}.get(str(난이도 or "").lower(), 난이도)
    if not await check_registered(ctx):
        return

    if 난이도 not in DUNGEONS:
        ctx.command.reset_cooldown(ctx)
        await ctx.send("⚠️ 사용법: `!던전 약함/보통/강함/지옥` · English: `!dungeon weak/normal/hard/hell`")
        return

    u = get_user(ctx.author.id)
    ensure_dungeon_user_state(u)
    refresh_conditions(u, get_max_hp)
    if u["conditions"].get("기절", 0) > 0:
        ctx.command.reset_cooldown(ctx)
        await ctx.send("😵 기절 상태라 던전에 갈 수 없습니다. `!병원`에서 치료하세요.")
        return
    d = DUNGEONS[난이도]
    stamina_cost = DUNGEON_STAMINA_COSTS[난이도]
    if not spend_stamina(u, stamina_cost):
        ctx.command.reset_cooldown(ctx)
        await ctx.send(
            f"⚡ 스태미나가 부족합니다. **{stamina_cost}** 필요 / 현재 **{u['stamina']}**\n"
            "`!휴식` 또는 시간이 지난 뒤 다시 도전하세요."
        )
        return
    monster = random.choice(d["monsters"])

    user_power = calculate_user_power(u)
    monster_power = max(1, int(d["base_power"] * random.uniform(0.85, 1.25)))

    pet_bonus = get_pet_bonuses(u)
    crit = random.random() < min(0.45, 0.08 + u["level"] * 0.003 + pet_bonus["crit"])
    dodge = random.random() < min(0.40, 0.06 + pet_bonus["dodge"])

    weather_mult, weather_state = weather_combat_multiplier(ctx.guild.id if ctx.guild else 0)
    fortune = active_fortune_modifiers(u)
    effective_power = int(user_power * (1.7 if crit else 1.0) * weather_mult * float(fortune.get("combat", 1.0)))
    power_ratio = effective_power / max(monster_power, 1)

    # v6.3.5a: 압도적인 전투력 차이에서도 고정 20% 패배가 발생하던 판정을 수정합니다.
    # 적 전투력의 2배 이상이면 확정 승리하고, 그 미만 구간만 확률 판정을 사용합니다.
    if power_ratio >= 2.0:
        victory_chance = 1.0
    else:
        victory_chance = 0.12 + min(0.68, power_ratio * 0.50)
        if effective_power >= monster_power:
            victory_chance = max(victory_chance, 0.88)
        if dodge:
            victory_chance += 0.10
        victory_chance += pet_bonus["victory"]

        # 부상·감염은 영향을 주되, 우세 전투력을 완전히 무효화하지 않도록 전투 패널티를 제한합니다.
        combat_condition_modifier = max(0.75, exploration_modifier(u))
        victory_chance *= combat_condition_modifier
        victory_chance = min(0.98, max(0.05, victory_chance))

    victory = random.random() < victory_chance

    await ctx.send(
        f"⚔️ **[{d['name']}]**\n"
        f"🚨 {monster['name']} 출현!\n"
        f"내 전투력: **{user_power}** / 적 전투력: **{monster_power}**\n"
        f"🎯 최종 승리 확률: **{victory_chance * 100:.1f}%**\n"
        f"{weather_state['emoji']} 날씨: **{weather_state['name']}** · 전투 효율 ×{weather_mult:.2f}\n"
        f"🌟 운세 전투 보정: **×{float(fortune.get('combat', 1.0)):.2f}**"
    )
    await asyncio.sleep(1.5)

    if victory:
        reward = int(d["reward"] * random.uniform(0.85, 1.25) * (1.0 + pet_bonus["reward"]) * float(fortune.get("reward", 1.0)))
        u["balance"] += reward
        u["stats"]["earned"] += reward
        u["stats"]["dungeon_wins"] += 1
        u.setdefault("dungeon_monster_kills", {})
        u["dungeon_monster_kills"][monster["name"]] = u["dungeon_monster_kills"].get(monster["name"], 0) + 1
        progress_quest(u, "던전 승리")
        progress_weekly(u, "던전 승리")
        add_season_points(u, {"약함": 5, "보통": 8, "강함": 12, "지옥": 20}[난이도])

        gained = random_materials(난이도)
        pet_material = None
        if random.random() < pet_bonus["material"]:
            pet_material = random.choice(MATERIALS)
            gained[pet_material] = gained.get(pet_material, 0) + 1
        give_materials(u, gained)

        drop_message = ""
        drop_chance = {
            "약함": 0.12,
            "보통": 0.18,
            "강함": 0.26,
            "지옥": 0.38
        }[난이도]

        if random.random() < drop_chance:
            tier, dropped_item = select_drop(d["drop_tiers"])
            if dropped_item not in u["inventory"]:
                u["inventory"].append(dropped_item)
                u["enhancements"][dropped_item] = 0
                drop_message = f"\n🎁 장비 드롭: **[{tier}] {dropped_item}**"
            else:
                duplicate_reward = ITEM_DB[tier][dropped_item]["price"] // 5
                u["balance"] += duplicate_reward
                drop_message = f"\n♻️ 중복 장비 환전: **{duplicate_reward:,}개**"

        event_text = []
        if crit:
            event_text.append("💥 크리티컬")
        if dodge:
            event_text.append("💨 회피")
        event_line = " / ".join(event_text) if event_text else "정면 승부"

        materials_text = ", ".join(f"{k} {v}개" for k, v in gained.items())
        battle_damage = 0 if dodge else random.randint(1, {
            "약함": 5, "보통": 9, "강함": 14, "지옥": 20
        }[난이도])
        damage_taken, knocked_out = apply_damage(u, battle_damage)
        pet_healed = 0
        if pet_bonus["heal"] > 0 and u.get("hp", 0) > 0:
            pet_healed = min(pet_bonus["heal"], max(0, get_max_hp(u) - u["hp"]))
            u["hp"] += pet_healed
        pet_exp = {"약함": 8, "보통": 12, "강함": 18, "지옥": 28}[난이도]
        pet_level_ups = gain_pet_exp(u, pet_exp)
        condition_events = apply_dungeon_conditions(u, 난이도, True)
        weapon_state = consume_weapon_durability(u, {"약함": 1, "보통": 1, "강함": 2, "지옥": 3}[난이도])
        unlocked = check_achievements(u)
        save_data()

        msg = (
            f"🎉 **[승리]** {event_line}\n"
            f"🥫 식량 +{reward:,}개\n"
            f"🧰 재료: {materials_text}"
            f"{drop_message}\n"
            f"❤️ 전투 피해: **-{damage_taken}** | HP **{u['hp']} / {get_max_hp(u)}**\n"
            f"⚡ 스태미나: **-{stamina_cost}** | 현재 **{u['stamina']} / {get_max_stamina(u)}**"
        )
        if pet_material:
            msg += f"\n🐾 펫이 추가 재료 **{pet_material} 1개**를 발견했습니다."
        if pet_healed:
            msg += f"\n🐾 펫의 능력으로 HP **+{pet_healed}** 회복"
        if u.get("pet"):
            msg += f"\n✨ 펫 경험치 **+{pet_exp}**"
            if pet_level_ups:
                msg += f" · 레벨 **+{pet_level_ups}**"
        if condition_events:
            msg += "\n⚠️ " + " / ".join(condition_events)
        msg += f"\n🦠 감염도 **{u['infection']}%** | {condition_text(u)}"
        if weapon_state.get("name"):
            msg += f"\n🔧 {weapon_state['name']} 내구도 **{weapon_state['current']} / {weapon_state['maximum']} · {weapon_state['label']}**"
        if unlocked:
            msg += "\n🏆 업적 달성: " + ", ".join(x[0] for x in unlocked)
        await ctx.send(msg)
    else:
        penalty = int(d["reward"] * random.uniform(0.18, 0.35))
        damage = random.randint({"약함": 12, "보통": 20, "강함": 30, "지옥": 42}[난이도],
                                {"약함": 24, "보통": 36, "강함": 50, "지옥": 70}[난이도])
        damage_taken, knocked_out = apply_damage(u, damage)
        u["balance"] -= penalty
        u["stats"]["dungeon_losses"] += 1
        pet_exp = {"약함": 3, "보통": 5, "강함": 7, "지옥": 10}[난이도]
        pet_level_ups = gain_pet_exp(u, pet_exp)
        condition_events = apply_dungeon_conditions(u, 난이도, False)
        weapon_state = consume_weapon_durability(u, {"약함": 2, "보통": 2, "강함": 3, "지옥": 4}[난이도])
        save_data()

        knockout_text = (
            "\n🚑 HP가 0이 되어 구조대에게 발견됐습니다. "
            f"HP가 **{u['hp']}**까지 회복됐습니다."
            if knocked_out else ""
        )
        await ctx.send(
            f"💀 **[패배]** 식량 **{penalty:,}개** 상실.\n"
            f"❤️ 피해 **-{damage_taken}** | HP **{u['hp']} / {get_max_hp(u)}**\n"
            f"⚡ 스태미나 **-{stamina_cost}** | 현재 **{u['stamina']} / {get_max_stamina(u)}**\n"
            f"현재 잔액: **{u['balance']:,}개**"
            f"{knockout_text}"
            + (f"\n✨ 펫 경험치 **+{pet_exp}**" + (f" · 레벨 **+{pet_level_ups}**" if pet_level_ups else "") if u.get("pet") else "")
            + ("\n⚠️ " + " / ".join(condition_events) if condition_events else "")
            + f"\n🦠 감염도 **{u['infection']}%** | {condition_text(u)}"
            + (f"\n🔧 {weapon_state['name']} 내구도 **{weapon_state['current']} / {weapon_state['maximum']} · {weapon_state['label']}**" if weapon_state.get("name") else "")
        )


# =========================================================
# 서버 레이드
# =========================================================
@bot.hybrid_command()
async def 레이드(ctx):
    if not await check_registered(ctx):
        return

    boss = get_server_boss(ctx.guild.id)
    await ctx.send(
        f"👹 **[서버 레이드] {boss['name']}**\n"
        f"HP: **{boss['hp']:,} / {boss['max_hp']:,}**\n"
        "`!레이드공격`으로 공격하세요. 쿨타임 60초."
    )


@bot.hybrid_command()
@commands.cooldown(1, 60, commands.BucketType.user)
async def 레이드공격(ctx):
    if not await check_registered(ctx):
        return

    u = get_user(ctx.author.id)
    boss = get_server_boss(ctx.guild.id)

    base = calculate_user_power(u)
    damage = random.randint(max(1, base // 2), max(2, int(base * 1.4)))
    critical = random.random() < 0.15

    if critical:
        damage *= 2

    damage = min(damage, boss["hp"])
    boss["hp"] -= damage
    weapon_state = consume_weapon_durability(u, 1)

    uid = str(ctx.author.id)
    boss["participants"][uid] = boss["participants"].get(uid, 0) + damage
    u["stats"]["boss_damage"] += damage

    message = (
        f"⚔️ {ctx.author.mention} 공격!\n"
        f"데미지: **{damage:,}**{' 💥크리티컬' if critical else ''}\n"
        f"보스 HP: **{boss['hp']:,} / {boss['max_hp']:,}**"
        + (f"\n🔧 {weapon_state['name']} 내구도 **{weapon_state['current']} / {weapon_state['maximum']}**" if weapon_state.get("name") else "")
    )

    if boss["hp"] <= 0:
        participants = boss["participants"]
        total_damage = sum(participants.values())

        for participant_id, dealt in participants.items():
            pu = get_user(participant_id)
            if not pu:
                continue

            reward = 5000 + int(25000 * (dealt / max(1, total_damage)))
            pu["balance"] += reward
            pu["stats"]["earned"] += reward

        killer_reward = 10000
        u["balance"] += killer_reward
        u["stats"]["earned"] += killer_reward
        add_title(u, "레이드 최후의 일격")

        guild_id = str(ctx.guild.id)
        del world_data["server_bosses"][guild_id]
        message += (
            f"\n\n🏆 **레이드 보스 처치!**\n"
            f"참가자 보상 분배 완료.\n"
            f"마지막 일격 추가 보상: **{killer_reward:,}개**"
        )

    unlocked = check_achievements(u)
    save_data()

    if unlocked:
        message += "\n🏆 업적 달성: " + ", ".join(x[0] for x in unlocked)
    await ctx.send(message)


# =========================================================
# 전 서버 월드보스 V2.0-8
# =========================================================
def _world_boss_rows(boss):
    rows = []
    for uid, record in boss.get("participants", {}).items():
        if isinstance(record, dict):
            rows.append((uid, int(record.get("damage", 0)), int(record.get("attacks", 0))))
        else:
            rows.append((uid, int(record), 0))
    return sorted(rows, key=lambda x: x[1], reverse=True)


def _world_boss_bar(hp, max_hp, size=18):
    ratio = max(0.0, min(1.0, hp / max(1, max_hp)))
    filled = int(ratio * size)
    return "█" * filled + "░" * (size - filled)


def _grant_world_boss_drop(u, boss, rank):
    material = boss.get("material", "고대파편")
    material_amount = max(1, 8 - min(rank, 7))
    u.setdefault("materials", {})[material] = u.setdefault("materials", {}).get(material, 0) + material_amount

    item = None
    roll = random.random()
    if rank == 1 and roll < 0.18:
        item = random.choice(list(ITEM_DB["전설"].keys()))
    elif rank <= 3 and roll < 0.08:
        item = random.choice(list(ITEM_DB["영웅"].keys()))
    elif roll < 0.02:
        item = random.choice(list(ITEM_DB["희귀"].keys()))
    if item:
        u.setdefault("inventory", []).append(item)
    return material, material_amount, item


@bot.hybrid_command(name="월드보스", aliases=["보스현황"])
async def 월드보스(ctx):
    if not await check_registered(ctx):
        return

    boss = migrate_world_boss(world_data.get("world_boss"))
    world_data["world_boss"] = boss
    rows = _world_boss_rows(boss)
    ranking = [f"{i}. <@{uid}> — **{damage:,}** 피해 / {attacks}회" for i, (uid, damage, attacks) in enumerate(rows[:5], 1)]
    rank_text = "\n".join(ranking) if ranking else "아직 참가자 없음"
    percent = boss["hp"] / max(1, boss["max_hp"]) * 100
    status = "전투 중" if boss.get("status") == "active" and boss["hp"] > 0 else "처치 완료"

    await ctx.send(
        f"🌍 **[{boss['grade']} 월드보스] {boss['name']}**\n"
        f"상태: **{status}** | 특성: **{boss['trait']}**\n"
        f"HP: **{boss['hp']:,} / {boss['max_hp']:,}** ({percent:.1f}%)\n"
        f"`{_world_boss_bar(boss['hp'], boss['max_hp'])}`\n\n"
        f"🏅 **누적 피해 TOP 5**\n{rank_text}\n\n"
        "공격: `!보스공격` 또는 `!월드보스공격` · 개인 쿨타임 5분"
    )


@bot.hybrid_command(name="보스랭킹", aliases=["월드보스랭킹"])
async def 보스랭킹(ctx):
    if not await check_registered(ctx):
        return
    boss = migrate_world_boss(world_data.get("world_boss"))
    rows = _world_boss_rows(boss)
    if not rows:
        await ctx.send("📭 아직 월드보스 공격 기록이 없습니다.")
        return
    lines = [f"{i}. <@{uid}> — **{damage:,}** 피해 / {attacks}회" for i, (uid, damage, attacks) in enumerate(rows[:20], 1)]
    await ctx.send(f"🏆 **{boss['name']} 피해 랭킹**\n" + "\n".join(lines))


@bot.hybrid_command(name="월드보스공격", aliases=["보스공격"])
@commands.cooldown(1, 300, commands.BucketType.user)
async def 월드보스공격(ctx):
    if not await check_registered(ctx):
        return

    u = get_user(ctx.author.id)
    boss = migrate_world_boss(world_data.get("world_boss"))
    world_data["world_boss"] = boss
    u.setdefault("worldboss_codex", {})
    codex = u["worldboss_codex"].setdefault(boss["name"], {"damage": 0, "attacks": 0, "kills": 0})

    if boss.get("status") != "active" or boss["hp"] <= 0:
        ctx.command.reset_cooldown(ctx)
        await ctx.send("⚠️ 월드보스가 이미 처치되었습니다. 다음 소환을 기다려 주세요.")
        return

    power = max(1, calculate_user_power(u))
    trait = boss.get("trait", "")
    defense_rate = 0.18 if trait in {"중장갑", "전자 방벽"} else 0.08
    damage = random.randint(max(1, int(power * 1.4)), max(2, int(power * 3.6)))
    damage = max(1, int(damage * (1.0 - defense_rate)))

    totals = equipment_totals(u)
    critical_rate = min(0.35, 0.10 + totals.get("치명타", 0) / 250)
    critical = random.random() < critical_rate
    if critical:
        damage = int(damage * 2.5)

    pattern_text = ""
    hp_ratio = boss["hp"] / max(1, boss["max_hp"])
    if hp_ratio <= 0.30:
        damage = int(damage * 1.20)
        pattern_text = "\n🔥 보스가 광폭화했습니다! 가한 피해도 20% 증가합니다."
    if random.random() < 0.14:
        trait = boss.get("trait", "")
        if trait in {"중장갑", "전자 방벽", "피의 장막"}:
            damage = max(1, int(damage * 0.55))
            pattern_text += f"\n🛡️ **{trait}** 패턴으로 피해가 감소했습니다."
        elif trait in {"재생"}:
            heal = min(int(boss["max_hp"] * 0.015), boss["max_hp"] - boss["hp"])
            boss["hp"] += heal
            pattern_text += f"\n💚 **재생** 패턴: HP {heal:,} 회복."
        elif trait in {"감염폭풍", "광폭화"}:
            infection = random.randint(2, 6)
            u["infection"] = min(100, u.get("infection", 0) + infection)
            pattern_text += f"\n☣️ **{trait}** 패턴: 감염도 +{infection}."

    damage = min(damage, boss["hp"])
    boss["hp"] -= damage
    uid = str(ctx.author.id)
    record = boss["participants"].setdefault(uid, {"damage": 0, "attacks": 0, "last_hit": False})
    record["damage"] += damage
    record["attacks"] += 1
    u.setdefault("stats", {}).setdefault("worldboss_damage", 0)
    u["stats"]["worldboss_damage"] += damage
    codex["damage"] += damage
    codex["attacks"] += 1

    message = (
        f"⚔️ {ctx.author.mention}이(가) **{boss['name']}**을 공격했습니다!\n"
        f"피해량: **{damage:,}**{' 💥 치명타!' if critical else ''}\n"
        f"남은 HP: **{boss['hp']:,} / {boss['max_hp']:,}**"
        f"{pattern_text}"
    )

    if boss["hp"] <= 0:
        boss["status"] = "defeated"
        boss["defeated_at"] = datetime.now().isoformat()
        record["last_hit"] = True
        rows = _world_boss_rows(boss)
        total_damage = sum(row[1] for row in rows)
        reward_lines = []

        for rank, (participant_id, dealt, attacks) in enumerate(rows, 1):
            pu = get_user(participant_id)
            if not pu:
                continue
            participation = 12000
            share = int(90000 * dealt / max(1, total_damage))
            rank_bonus = 50000 if rank == 1 else 25000 if rank <= 3 else 8000 if rank <= 10 else 0
            food = participation + share + rank_bonus
            exp = 600 + max(0, 2200 - (rank - 1) * 150)
            pu["balance"] = pu.get("balance", 0) + food
            pu["exp"] = pu.get("exp", 0) + exp
            pu.setdefault("stats", {}).setdefault("earned", 0)
            pu["stats"]["earned"] += food
            material, material_amount, item = _grant_world_boss_drop(pu, boss, rank)
            if rank == 1:
                add_title(pu, "월드보스 1위")
            elif rank <= 3:
                add_title(pu, "월드보스 정복자")
            if participant_id == uid:
                reward_lines.append(f"내 보상: 식량 **{food:,}** · 경험치 **{exp:,}** · {material} **{material_amount}개**")
                if item:
                    reward_lines.append(f"🎁 특별 장비 획득: **{item}**")

        add_title(u, "종말을 끝낸 자")
        codex["kills"] += 1
        message += "\n\n🏆 **월드보스 처치! 참가자 전원에게 기여도 보상이 지급되었습니다.**"
        if reward_lines:
            message += "\n" + "\n".join(reward_lines)

    unlocked = check_achievements(u)
    save_data()
    if unlocked:
        message += "\n🏆 업적 달성: " + ", ".join(x[0] for x in unlocked)
    await ctx.send(message)


async def _require_world_boss_admin(ctx):
    if ctx.guild and (ctx.author == ctx.guild.owner or ctx.author.guild_permissions.administrator):
        return True
    await ctx.send("❌ 관리자 전용 명령어입니다.")
    return False


@bot.hybrid_command(name="월드보스리셋", aliases=["월드보스소환"])
async def 월드보스리셋(ctx, *, 보스이름: str = None):
    if not await _require_world_boss_admin(ctx):
        return
    boss = create_world_boss(보스이름)
    world_data["world_boss"] = boss
    save_data()
    await ctx.send(f"🌍 **{boss['grade']} 월드보스 {boss['name']}**이(가) 소환되었습니다!\nHP: **{boss['max_hp']:,}** · 특성: **{boss['trait']}**")


@bot.hybrid_command(name="월드보스체력")
async def 월드보스체력(ctx, 체력: int):
    if not await _require_world_boss_admin(ctx):
        return
    if 체력 < 1:
        await ctx.send("⚠️ 체력은 1 이상이어야 합니다.")
        return
    boss = migrate_world_boss(world_data.get("world_boss"))
    boss["max_hp"] = 체력
    boss["hp"] = 체력
    boss["status"] = "active"
    world_data["world_boss"] = boss
    save_data()
    await ctx.send(f"❤️ 월드보스 체력을 **{체력:,}**으로 설정했습니다.")


@bot.hybrid_command(name="월드보스종료")
async def 월드보스종료(ctx):
    if not await _require_world_boss_admin(ctx):
        return
    boss = migrate_world_boss(world_data.get("world_boss"))
    boss["hp"] = 0
    boss["status"] = "defeated"
    boss["defeated_at"] = datetime.now().isoformat()
    world_data["world_boss"] = boss
    save_data()
    await ctx.send(f"🛑 **{boss['name']}** 월드보스를 관리자 권한으로 종료했습니다.")


# =========================================================
# 일일 퀘스트 / 업적 / 칭호
# =========================================================
@bot.hybrid_command()
async def 일일퀘스트(ctx):
    if not await check_registered(ctx):
        return

    u = get_user(ctx.author.id)
    q = u["daily_quest"]
    status = "완료" if q["progress"] >= q["target"] else "진행 중"
    claimed = " / 보상 수령 완료" if q["claimed"] else ""

    await ctx.send(
        f"📌 **[오늘의 퀘스트]**\n"
        f"내용: **{q['type']} {q['target']}회**\n"
        f"진행: **{q['progress']} / {q['target']}**\n"
        f"보상: **식량 {q['reward']:,}개**\n"
        f"상태: **{status}{claimed}**"
    )


@bot.hybrid_command()
async def 퀘스트보상(ctx):
    if not await check_registered(ctx):
        return

    u = get_user(ctx.author.id)
    q = u["daily_quest"]

    if q["claimed"]:
        await ctx.send("⚠️ 오늘의 퀘스트 보상은 이미 받았습니다.")
        return
    if q["progress"] < q["target"]:
        await ctx.send("⚠️ 아직 퀘스트를 완료하지 못했습니다.")
        return

    q["claimed"] = True
    u["balance"] += q["reward"]
    u["stats"]["earned"] += q["reward"]
    save_data()

    await ctx.send(f"🎁 퀘스트 보상 **{q['reward']:,}개** 수령 완료!")


@bot.hybrid_command()
async def 업적(ctx):
    if not await check_registered(ctx):
        return

    u = get_user(ctx.author.id)
    check_achievements(u)
    save_data()

    text = "🏆 **[업적]**\n"
    for name, (stat_key, target, title) in ACHIEVEMENTS.items():
        done = "✅" if name in u["achievements"] else "⬜"
        progress = min(u["stats"].get(stat_key, 0), target)
        text += (
            f"{done} **{name}** — {progress:,}/{target:,} "
            f"| 칭호: {title}\n"
        )

    await send_pages(ctx.channel, text)


@bot.hybrid_command()
async def 칭호목록(ctx):
    if not await check_registered(ctx):
        return

    u = get_user(ctx.author.id)
    await send_pages(
        ctx.channel,
        "🏷️ **[보유 칭호]**\n" + "\n".join(f"• {x}" for x in u["titles"])
    )


@bot.hybrid_command()
async def 칭호(ctx, *, 칭호이름: str):
    if not await check_registered(ctx):
        return

    u = get_user(ctx.author.id)

    if 칭호이름 not in u["titles"]:
        await ctx.send("⚠️ 보유하지 않은 칭호입니다.")
        return

    u["title"] = 칭호이름
    save_data()
    await ctx.send(f"🏷️ 대표 칭호를 **{칭호이름}**으로 변경했습니다.")


# =========================================================
# 시즌 랭킹
# =========================================================
@bot.hybrid_command()
async def 랭킹(ctx):
    if not await check_registered(ctx):
        return

    ranking = sorted(
        user_data.items(),
        key=lambda x: calculate_user_power(migrate_user(x[1])),
        reverse=True
    )[:10]

    lines = []
    for i, (uid, u) in enumerate(ranking, 1):
        lines.append(
            f"{i}. <@{uid}> | {u['title']} | "
            f"전투력 **{calculate_user_power(u):,}** | Lv.{u['level']}"
        )

    await ctx.send(
        f"🏆 **[{world_data['season']} 시즌 전투력 랭킹]**\n" +
        ("\n".join(lines) if lines else "랭킹 데이터 없음")
    )


# =========================================================
# 도박 시스템
# =========================================================
async def _legacy_탐색_v1(ctx, 방향: str, 배팅액: int):
    if not await check_registered(ctx):
        return

    u = get_user(ctx.author.id)

    if 방향 not in ["왼쪽", "오른쪽"]:
        ctx.command.reset_cooldown(ctx)
        await ctx.send("⚠️ 사용법: `!탐색 왼쪽 1000`")
        return
    if 배팅액 <= 0 or u["balance"] < 배팅액:
        ctx.command.reset_cooldown(ctx)
        await ctx.send("⚠️ 배팅액이 잘못됐거나 식량이 부족합니다.")
        return

    u["stats"]["gambles"] += 1
    progress_quest(u, "도박 참여")

    if random.random() < 0.5:
        reward = 배팅액 * random.choice([1, 1, 2, 3])
        u["balance"] += reward
        u["stats"]["earned"] += reward
        result = f"📦 성공! 식량 **{reward:,}개** 획득."
    else:
        u["balance"] -= 배팅액
        result = f"🩸 실패! 식량 **{배팅액:,}개** 상실."

    save_data()
    await ctx.send(result)


async def _legacy_주파수_v1(ctx, 배팅액: int):
    if not await check_registered(ctx):
        return

    u = get_user(ctx.author.id)

    if 배팅액 <= 0 or u["balance"] < 배팅액:
        ctx.command.reset_cooldown(ctx)
        await ctx.send("⚠️ 배팅액이 잘못됐거나 잔액이 부족합니다.")
        return

    signals = ["🔴", "🟢", "🔵", "⚡", "💀"]
    result = [random.choice(signals) for _ in range(3)]
    screen = f"**[ {' | '.join(result)} ]**\n"

    u["stats"]["gambles"] += 1
    progress_quest(u, "도박 참여")

    if len(set(result)) == 1:
        if result[0] == "💀":
            loss = 배팅액 * 3
            u["balance"] -= loss
            message = f"☠️ 저주받은 신호! **{loss:,}개** 상실."
        else:
            multiplier = random.randint(5, 20)
            gain = 배팅액 * multiplier
            u["balance"] += gain
            u["stats"]["earned"] += gain
            message = f"📡 잭팟 {multiplier}배! **{gain:,}개** 획득."
    elif len(set(result)) == 2:
        gain = 배팅액 // 2
        u["balance"] += gain
        u["stats"]["earned"] += gain
        message = f"📻 부분 일치! **{gain:,}개** 획득."
    else:
        u["balance"] -= 배팅액
        message = f"📵 통신 실패! **{배팅액:,}개** 상실."

    save_data()
    await ctx.send(screen + message)


roulette_state = {}


async def _legacy_룰렛_v1(ctx, 배팅액: int):
    if not await check_registered(ctx):
        return

    u = get_user(ctx.author.id)

    if 배팅액 <= 0 or u["balance"] < 배팅액:
        ctx.command.reset_cooldown(ctx)
        await ctx.send("⚠️ 배팅액이 잘못됐거나 잔액이 부족합니다.")
        return

    guild_id = str(ctx.guild.id)
    if guild_id not in roulette_state:
        roulette_state[guild_id] = {
            "bullet": random.randint(1, 6),
            "chamber": 1
        }

    state = roulette_state[guild_id]
    u["stats"]["gambles"] += 1
    progress_quest(u, "도박 참여")

    if state["chamber"] == state["bullet"]:
        u["balance"] -= 배팅액
        del roulette_state[guild_id]
        result = f"💥 **탕!** 식량 **{배팅액:,}개** 상실."
    else:
        multiplier = random.randint(2, 8)
        gain = 배팅액 * multiplier
        u["balance"] += gain
        u["stats"]["earned"] += gain
        state["chamber"] += 1
        result = f"💨 생존! {multiplier}배 보상 **{gain:,}개** 획득."

    save_data()
    await ctx.send(result)


async def _legacy_파산신청_v1(ctx):
    if not await check_registered(ctx):
        return

    u = get_user(ctx.author.id)

    if u["balance"] >= 0:
        ctx.command.reset_cooldown(ctx)
        await ctx.send("⚠️ 빚이 없어 파산 신청이 불가능합니다.")
        return

    debt = abs(u["balance"])
    rate = random.randint(10, 100)
    forgiven = int(debt * rate / 100)
    u["balance"] += forgiven

    if u["balance"] > 0:
        u["balance"] = 0

    save_data()

    await ctx.send(
        f"⚖️ 빚의 **{rate}%** 탕감!\n"
        f"남은 빚: **{abs(min(0, u['balance'])):,}개**"
    )


# =========================================================
# 관리자 명령어
# =========================================================
@bot.hybrid_command()
async def 가방조회(ctx, 대상: discord.Member):
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ 관리자 전용 명령어입니다.")
        return

    u = get_user(대상.id)
    if not u:
        await ctx.send("⚠️ 가입하지 않은 유저입니다.")
        return

    await ctx.send(
        f"🔍 **[{대상.name}]**\n"
        f"식량: {u['balance']:,}개\n"
        f"레벨: {u['level']}\n"
        f"전투력: {calculate_user_power(u)}\n"
        f"장착 장비: {', '.join(x for x in u.get('equipment', {}).values() if x) or '없음'}"
    )


@bot.hybrid_command()
async def 식량지급(ctx, 대상: discord.Member, 금액: int):
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ 관리자 전용 명령어입니다.")
        return

    u = get_user(대상.id)
    if not u:
        await ctx.send("⚠️ 가입하지 않은 유저입니다.")
        return
    if 금액 <= 0:
        await ctx.send("⚠️ 1 이상의 금액을 입력하세요.")
        return

    u["balance"] += 금액
    u["stats"]["earned"] += 금액
    save_data()

    await ctx.send(f"✅ {대상.mention}에게 식량 **{금액:,}개** 지급.")


@bot.hybrid_command()
async def 식량회수(ctx, 대상: discord.Member, 금액: int):
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ 관리자 전용 명령어입니다.")
        return

    u = get_user(대상.id)
    if not u:
        await ctx.send("⚠️ 가입하지 않은 유저입니다.")
        return
    if 금액 <= 0:
        await ctx.send("⚠️ 1 이상의 금액을 입력하세요.")
        return

    u["balance"] -= 금액
    save_data()

    await ctx.send(f"✅ {대상.mention}에게서 식량 **{금액:,}개** 회수.")



# =========================================================
# 채집 생활: 채집 / 낚시 / 벌목 / 광산
# =========================================================
LIFE_TABLES = {
    "채집": [
        ("약초", 1, 4, 50),
        ("고철", 1, 3, 40),
        ("식량", 300, 1200, 10),
    ],
    "낚시": [
        ("물고기", 1, 5, 75),
        ("식량", 500, 2500, 25),
    ],
    "벌목": [
        ("나무", 2, 6, 85),
        ("고철", 1, 2, 15),
    ],
    "광산": [
        ("광석", 2, 6, 75),
        ("고철", 1, 4, 20),
        ("식량", 1000, 4000, 5),
    ],
}


async def perform_life_activity(ctx, activity):
    if not await check_registered(ctx):
        return

    u = get_user(ctx.author.id)
    refresh_conditions(u, get_max_hp)
    if u["conditions"].get("기절", 0) > 0:
        if ctx.command:
            ctx.command.reset_cooldown(ctx)
        await ctx.send("😵 기절 상태라 생활 활동을 할 수 없습니다. `!병원`에서 치료하세요.")
        return
    stamina_cost = LIFE_STAMINA_COSTS[activity]
    if not spend_stamina(u, stamina_cost):
        if ctx.command:
            ctx.command.reset_cooldown(ctx)
        await ctx.send(
            f"⚡ 스태미나가 부족합니다. **{stamina_cost}** 필요 / 현재 **{u['stamina']}**\n"
            "`!휴식` 또는 시간이 지난 뒤 다시 시도하세요."
        )
        return
    guild_id = ctx.guild.id if ctx.guild else 0
    weather_reward, weather_fail, weather_rare, weather_state = weather_life_modifiers(guild_id)
    fortune_mods = active_fortune_modifiers(u)
    fortune_life = float(fortune_mods.get("life", 1.0))
    if random.random() < weather_fail:
        u.setdefault("life_mastery", {"채집": 0, "낚시": 0, "벌목": 0, "광산": 0})
        u["life_mastery"][activity] = int(u.get("life_mastery", {}).get(activity, 0)) + 1
        progress_weekly(u, "생활 활동")
        add_season_points(u, 2)
        save_data()
        fail_embed = discord.Embed(
            title=f"{weather_state['emoji']} {activity} 실패 · {weather_state['name']}",
            description="기상 악화로 현장 작업을 중단했습니다. 자원은 획득하지 못했지만 숙련도는 소폭 상승합니다.",
            color=discord.Color.orange(),
        )
        fail_embed.add_field(name="⚡ 스태미나", value=f"**-{stamina_cost}** · {u['stamina']}/{get_max_stamina(u)}", inline=True)
        fail_embed.add_field(name="🌦️ 환경 효과", value=weather_state['desc'], inline=False)
        await ctx.send(embed=fail_embed)
        return

    entries = LIFE_TABLES[activity]
    names = [x[0] for x in entries]
    weights = [x[3] for x in entries]
    selected = random.choices(entries, weights=weights, k=1)[0]
    name, minimum, maximum, _ = selected
    u.setdefault("life_mastery", {"채집": 0, "낚시": 0, "벌목": 0, "광산": 0})
    mastery_exp = int(u["life_mastery"].get(activity, 0))
    mastery_level = 1 + mastery_exp // 20
    mastery_bonus = min(0.30, (mastery_level - 1) * 0.02)
    supply_mult = 1.0
    supply_rare = 0.0
    try:
        from apocalypse_bot.commands.v639_frontier_operations import active_supply_drop
        supply_info = active_supply_drop(world_data, guild_id)
        supply_mult = float(supply_info.get("life_mult", 1.0))
        supply_rare = float(supply_info.get("rare_bonus", 0.0))
    except Exception:
        supply_mult = 1.0
        supply_rare = 0.0
    amount = max(1, int(random.randint(minimum, maximum) * exploration_modifier(u) * (1.0 + mastery_bonus) * weather_reward * fortune_life * supply_mult))
    u["life_mastery"][activity] = mastery_exp + 1

    rare_text = ""
    if name == "식량":
        u["balance"] += amount
        u["stats"]["earned"] += amount
        result = f"🥫 버려진 보급품 **{amount:,}개** 발견"
    else:
        u["resources"][name] = u["resources"].get(name, 0) + amount
        result = f"📦 **{name} {amount}개** 획득"

    if random.random() < min(0.24, 0.05 + weather_rare + supply_rare):
        u["materials"]["고대파편"] = u["materials"].get("고대파편", 0) + 1
        rare_text = "\n✨ 희귀 발견: **고대파편 1개**"

    progress_weekly(u, "생활 활동")
    add_season_points(u, 4)
    save_data()

    key_map = {"채집": "gathering", "벌목": "woodcutting", "낚시": "fishing", "광산": "mining"}
    visual_key = key_map[activity]
    stage2_activity = activity in {"낚시", "광산"}
    result_embed = discord.Embed(
        title=f"{ {'채집':'🌿','낚시':'🎣','벌목':'🪓','광산':'⛏️'}[activity] } {activity} 결과",
        description=result + rare_text,
        color=discord.Color.gold() if rare_text else discord.Color.green(),
    )
    result_embed.add_field(name="📦 이번 획득", value=(f"**식량 +{amount:,}**" if name == "식량" else f"**{name} +{amount}**"), inline=True)
    result_embed.add_field(name="📈 생활 숙련도", value=f"**Lv.{mastery_level}** · {int(u['life_mastery'][activity]) % 20}/20", inline=True)
    result_embed.add_field(name="⚡ 스태미나", value=f"**-{stamina_cost}** · {u['stamina']}/{get_max_stamina(u)}", inline=True)
    result_embed.add_field(name="🎬 현장 반응", value=("✨ 평범한 수확물과 다른 희귀 신호가 확인됐습니다." if rare_text else "✅ 확보한 자원을 분류해 기지 보급 목록에 등록했습니다."), inline=False)
    fortune_text = " · 오늘의 운세 미확인" if not fortune_mods.get("active") else f" · 운세 ×{fortune_life:.2f}"
    supply_text = f" · 🎁 보급선 ×{supply_mult:.1f}" if supply_mult > 1.0 else ""
    result_embed.add_field(name="🌦️ 종말 날씨", value=f"{weather_state['emoji']} **{weather_state['name']}** · 날씨 ×{weather_reward:.2f}{fortune_text}{supply_text}", inline=False)
    tip_getter = getattr(bot, "v632_tip", None) if stage2_activity else getattr(bot, "v631_tip", None)
    result_embed.add_field(name="💡 TIP", value=(tip_getter(visual_key) if tip_getter else "생활 숙련도가 오르면 획득량이 증가합니다."), inline=False)
    visual_send = getattr(bot, "v632_send_visual", None) if stage2_activity else getattr(bot, "v631_send_visual", None)
    asset_kind = "rare" if rare_text else "success"
    if visual_send:
        result_message = await visual_send(ctx, result_embed, f"activities/{visual_key}/{asset_kind}")
    else:
        result_message = await ctx.send(embed=result_embed)
    for emoji in (("💎", "✨") if rare_text else ("✅", "📦")):
        try:
            await result_message.add_reaction(emoji)
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            break
    maybe_encounter = getattr(bot, "v632_maybe_encounter", None) if stage2_activity else getattr(bot, "v631_maybe_encounter", None)
    if maybe_encounter:
        await maybe_encounter(ctx, visual_key, u)


@bot.hybrid_command()
@commands.cooldown(1, 120, commands.BucketType.user)
async def 채집(ctx):
    await perform_life_activity(ctx, "채집")


@bot.hybrid_command()
@commands.cooldown(1, 120, commands.BucketType.user)
async def 낚시(ctx):
    await perform_life_activity(ctx, "낚시")


@bot.hybrid_command()
@commands.cooldown(1, 120, commands.BucketType.user)
async def 벌목(ctx):
    await perform_life_activity(ctx, "벌목")


@bot.hybrid_command()
@commands.cooldown(1, 120, commands.BucketType.user)
async def 광산(ctx):
    await perform_life_activity(ctx, "광산")


@bot.hybrid_command()
async def 자원(ctx):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    lines = [f"• {name}: **{amount}개**" for name, amount in u["resources"].items()]
    await ctx.send("🌲 **[생활 자원]**\n" + "\n".join(lines))


# =========================================================
# 기지 건설 / 강화 / 수확
# =========================================================
BASE_BUILD_COST = {"나무": 120, "광석": 80, "고철": 100, "food": 100_000}

# key는 현재 레벨입니다. 상위 기지일수록 자원과 대기 시간이 크게 증가합니다.
BASE_COSTS = {
    1: {"나무": 350, "광석": 250, "고철": 300, "food": 500_000, "seconds": 1_800},
    2: {"나무": 1_000, "광석": 800, "고철": 900, "food": 2_500_000, "seconds": 7_200},
    3: {"나무": 3_000, "광석": 2_500, "고철": 2_800, "food": 10_000_000, "seconds": 28_800},
    4: {"나무": 8_000, "광석": 7_000, "고철": 7_500, "food": 40_000_000, "seconds": 86_400},
}
BASE_NAMES = {0: "미건설", 1: "야영지", 2: "임시 거점", 3: "강화 거점", 4: "중형 기지", 5: "요새급 기지"}
BASE_HOURLY = {0: 0, 1: 320, 2: 750, 3: 1_600, 4: 3_200, 5: 6_500}


def _base_cost_text(cost):
    return (
        f"나무 **{cost['나무']:,}** · 광석 **{cost['광석']:,}** · "
        f"고철 **{cost['고철']:,}** · 식량 **{cost['food']:,}**"
    )


def _base_missing(u, cost):
    missing = []
    for resource in ("나무", "광석", "고철"):
        current = int(u.get("resources", {}).get(resource, 0))
        if current < int(cost[resource]):
            missing.append(f"{resource} **{int(cost[resource]) - current:,}개**")
    balance = int(u.get("balance", 0))
    if balance < int(cost["food"]):
        missing.append(f"식량 **{int(cost['food']) - balance:,}개**")
    return missing


def _base_upgrade_remaining(base):
    target = int(base.get("upgrade_target", 0) or 0)
    complete_at = parse_iso(base.get("upgrade_complete_at"))
    if target <= 0 or complete_at is None:
        return 0, 0.0
    return target, (complete_at - datetime.now()).total_seconds()


def _finish_base_upgrade(base):
    target, remaining = _base_upgrade_remaining(base)
    if target <= 0 or remaining > 0:
        return False
    base["level"] = max(int(base.get("level", 1)), target)
    base["upgrade_target"] = 0
    base["upgrade_started_at"] = ""
    base["upgrade_complete_at"] = ""
    return True


async def _send_base_embed(ctx, embed, file=None):
    if file:
        return await ctx.send(embed=embed, file=file)
    return await ctx.send(embed=embed)


@bot.hybrid_command()
async def 기지(ctx):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    base = u["base"]
    if _finish_base_upgrade(base):
        save_data()
    built = bool(base.get("built", False))
    level = int(base.get("level", 1) if built else 0)
    target, remaining = _base_upgrade_remaining(base)
    hourly = BASE_HOURLY.get(level, level * 320) if built else 0
    embed = discord.Embed(
        title=f"🏠 {ctx.author.display_name}의 기지 · {BASE_NAMES.get(level, f'Lv.{level}')}",
        description="상위 단계일수록 요구 자원과 건설 시간이 급격히 증가합니다.",
        color=discord.Color.dark_gold(),
    )
    embed.add_field(name="상태", value="**건설 완료**" if built else "**미건설**", inline=True)
    embed.add_field(name="기지 레벨", value=f"**Lv.{level}/5**", inline=True)
    embed.add_field(name="시간당 생산", value=f"**{hourly:,} 식량**", inline=True)
    embed.add_field(name="저장 식량", value=f"**{int(base.get('storage', 0)):,}개**", inline=True)
    if target > 0 and remaining > 0:
        embed.add_field(
            name="🏗️ 업그레이드 진행 중",
            value=f"목표 **Lv.{target} · {BASE_NAMES.get(target)}**\n남은 시간 **{format_remaining(remaining)}**",
            inline=False,
        )
    elif built and level < 5:
        cost = BASE_COSTS[level]
        embed.add_field(
            name=f"다음 단계 · Lv.{level + 1} {BASE_NAMES[level + 1]}",
            value=f"{_base_cost_text(cost)}\n건설 시간 **{format_remaining(cost['seconds'])}**",
            inline=False,
        )
    file = apply_base_stage_visual(embed, level)
    await _send_base_embed(ctx, embed, file)


@bot.hybrid_command()
async def 기지건설(ctx):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    base = u["base"]
    if base.get("built", False):
        embed = discord.Embed(title="⚠️ 기지가 이미 건설되어 있습니다", color=discord.Color.orange())
        file = apply_base_stage_visual(embed, int(base.get("level", 1)))
        await _send_base_embed(ctx, embed, file)
        return

    missing = _base_missing(u, BASE_BUILD_COST)
    if missing:
        embed = discord.Embed(
            title="📦 기지 건설 자원 부족",
            description="부족한 자원: " + " · ".join(missing),
            color=discord.Color.red(),
        )
        embed.add_field(name="총 건설 비용", value=_base_cost_text(BASE_BUILD_COST), inline=False)
        embed.add_field(name="자원 확보", value="생활 활동 외에도 `!자원시장`·`!자원구매`·`!기지칩교환`을 사용할 수 있습니다.", inline=False)
        file = apply_base_reaction_visual(embed, "resource_shortage")
        await _send_base_embed(ctx, embed, file)
        return

    for resource in ("나무", "광석", "고철"):
        u["resources"][resource] -= int(BASE_BUILD_COST[resource])
    u["balance"] -= int(BASE_BUILD_COST["food"])
    base["built"] = True
    base["level"] = 1
    base["last_collect"] = datetime.now().isoformat()
    base["upgrade_target"] = 0
    base["upgrade_started_at"] = ""
    base["upgrade_complete_at"] = ""
    add_title(u, "기지 개척자")
    add_season_points(u, 30)
    save_data()
    embed = discord.Embed(
        title="🏠 기지 건설 완료 · Lv.1 야영지",
        description="첫 거점이 완성됐습니다. `!기지수확`으로 생산 식량을 회수할 수 있습니다.",
        color=discord.Color.green(),
    )
    embed.add_field(name="소모 자원", value=_base_cost_text(BASE_BUILD_COST), inline=False)
    file = apply_base_reaction_visual(embed, "build_start")
    await _send_base_embed(ctx, embed, file)


@bot.hybrid_command()
async def 기지강화(ctx):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    base = u["base"]
    if not base.get("built", False):
        embed = discord.Embed(title="⚠️ 먼저 `!기지건설`을 해야 합니다", color=discord.Color.orange())
        file = apply_base_stage_visual(embed, 0)
        await _send_base_embed(ctx, embed, file)
        return

    if _finish_base_upgrade(base):
        add_season_points(u, 60)
        save_data()
        level = int(base["level"])
        embed = discord.Embed(
            title=f"🏗️ 업그레이드 완료 · Lv.{level} {BASE_NAMES[level]}",
            description="긴 공사가 끝났습니다. 생산량과 기지 외형이 한 단계 성장했습니다.",
            color=discord.Color.green(),
        )
        embed.add_field(name="시간당 생산", value=f"**{BASE_HOURLY[level]:,} 식량**", inline=True)
        file = apply_base_reaction_visual(embed, "upgrade_success")
        await _send_base_embed(ctx, embed, file)
        return

    target, remaining = _base_upgrade_remaining(base)
    if target > 0 and remaining > 0:
        embed = discord.Embed(
            title=f"🏗️ 기지 업그레이드 진행 중 · Lv.{target}",
            description=f"남은 시간 **{format_remaining(remaining)}**\n완료 후 `!기지강화` 또는 `!기지`를 사용하면 상태가 갱신됩니다.",
            color=discord.Color.blue(),
        )
        file = apply_base_reaction_visual(embed, "upgrade_progress")
        await _send_base_embed(ctx, embed, file)
        return

    level = int(base.get("level", 1))
    if level >= 5:
        embed = discord.Embed(title="🏰 기지가 최대 단계입니다", description="Lv.5 요새급 기지까지 완성했습니다.", color=discord.Color.gold())
        file = apply_base_stage_visual(embed, 5)
        await _send_base_embed(ctx, embed, file)
        return

    cost = BASE_COSTS[level]
    missing = _base_missing(u, cost)
    if missing:
        embed = discord.Embed(
            title=f"📦 Lv.{level + 1} 업그레이드 자원 부족",
            description="부족한 자원: " + " · ".join(missing),
            color=discord.Color.red(),
        )
        embed.add_field(name="필요 자원", value=_base_cost_text(cost), inline=False)
        embed.add_field(name="필요 시간", value=f"**{format_remaining(cost['seconds'])}**", inline=True)
        embed.add_field(name="자원 확보", value="생활 활동 외에도 `!자원시장`·`!자원구매`·`!기지칩교환`을 사용할 수 있습니다.", inline=False)
        file = apply_base_reaction_visual(embed, "resource_shortage")
        await _send_base_embed(ctx, embed, file)
        return

    for resource in ("나무", "광석", "고철"):
        u["resources"][resource] -= int(cost[resource])
    u["balance"] -= int(cost["food"])
    now = datetime.now()
    target = level + 1
    base["upgrade_target"] = target
    base["upgrade_started_at"] = now.isoformat()
    base["upgrade_complete_at"] = (now + timedelta(seconds=int(cost["seconds"]))).isoformat()
    save_data()
    embed = discord.Embed(
        title=f"🛠️ 기지 업그레이드 시작 · Lv.{level} → Lv.{target}",
        description=f"목표 **{BASE_NAMES[target]}**\n완료까지 **{format_remaining(cost['seconds'])}**",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="소모 자원", value=_base_cost_text(cost), inline=False)
    embed.add_field(name="주의", value="공사 중에는 추가 업그레이드를 시작할 수 없습니다.", inline=False)
    file = apply_base_reaction_visual(embed, "upgrade_progress")
    await _send_base_embed(ctx, embed, file)


@bot.hybrid_command()
async def 기지수확(ctx):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    base = u["base"]
    if not base.get("built", False):
        embed = discord.Embed(title="⚠️ 먼저 기지를 건설하세요", color=discord.Color.orange())
        file = apply_base_stage_visual(embed, 0)
        await _send_base_embed(ctx, embed, file)
        return

    if _finish_base_upgrade(base):
        save_data()
    now = datetime.now()
    last = parse_iso(base.get("last_collect")) or now
    elapsed_hours = min(24.0, max(0.0, (now - last).total_seconds() / 3600.0))
    level = int(base.get("level", 1))
    reward = int(elapsed_hours * BASE_HOURLY.get(level, level * 320))
    if reward < 100:
        embed = discord.Embed(
            title="⏳ 아직 생산물이 부족합니다",
            description=f"누적 시간 **{int(elapsed_hours * 60)}분** · 최소 100 식량 이상 쌓인 뒤 수확할 수 있습니다.",
            color=discord.Color.orange(),
        )
        file = apply_base_reaction_visual(embed, "harvest_empty")
        await _send_base_embed(ctx, embed, file)
        return

    u["balance"] += reward
    u["stats"]["earned"] += reward
    base["last_collect"] = now.isoformat()
    add_season_points(u, min(25, int(elapsed_hours)))
    save_data()
    embed = discord.Embed(
        title="📦 기지 생산 수확 완료",
        description=f"Lv.{level} {BASE_NAMES[level]}에서 식량 **{reward:,}개**를 회수했습니다.",
        color=discord.Color.green(),
    )
    embed.add_field(name="가동 시간", value=f"**{elapsed_hours:.1f}시간**", inline=True)
    embed.add_field(name="현재 잔액", value=f"**{int(u['balance']):,} 식량**", inline=True)
    file = apply_base_reaction_visual(embed, "harvest_success")
    await _send_base_embed(ctx, embed, file)


# =========================================================
# 길드 시스템 · v7.5.1 통합 위임
# =========================================================
# 기존 HybridCommand 이름과 슬래시 진입점은 그대로 유지하면서 실제 처리는
# v7.5.1 길드 서비스로 위임합니다. 구형 길드 기금은 통합 금고 식량과 미러링됩니다.
from apocalypse_bot.commands.v750_guild_raid import (
    legacy_guild_create as _v750_guild_create,
    legacy_guild_donate as _v750_guild_donate,
    legacy_guild_info as _v750_guild_info,
    legacy_guild_join as _v750_guild_join,
    legacy_guild_leave as _v750_guild_leave,
    legacy_guild_list as _v750_guild_list,
    legacy_guild_upgrade as _v750_guild_upgrade,
)


@bot.hybrid_command()
async def 길드목록(ctx):
    await _v750_guild_list(ctx, world_data=world_data, check_registered=check_registered)


@bot.hybrid_command()
async def 길드생성(ctx, *, 길드명: str):
    await _v750_guild_create(
        ctx,
        name=길드명,
        world_data=world_data,
        get_user=get_user,
        check_registered=check_registered,
        save_data=save_data,
        add_title=add_title,
        add_season_points=add_season_points,
    )


@bot.hybrid_command()
async def 길드가입(ctx, *, 길드명: str):
    await _v750_guild_join(
        ctx,
        name=길드명,
        world_data=world_data,
        get_user=get_user,
        check_registered=check_registered,
        save_data=save_data,
    )


@bot.hybrid_command()
async def 길드정보(ctx):
    await _v750_guild_info(
        ctx,
        world_data=world_data,
        get_user=get_user,
        check_registered=check_registered,
        save_data=save_data,
    )


@bot.hybrid_command()
async def 길드기부(ctx, 금액: int):
    await _v750_guild_donate(
        ctx,
        amount=금액,
        world_data=world_data,
        get_user=get_user,
        check_registered=check_registered,
        save_data=save_data,
    )


@bot.hybrid_command()
async def 길드강화(ctx):
    await _v750_guild_upgrade(
        ctx,
        world_data=world_data,
        get_user=get_user,
        check_registered=check_registered,
        save_data=save_data,
    )


@bot.hybrid_command()
async def 길드탈퇴(ctx):
    await _v750_guild_leave(
        ctx,
        world_data=world_data,
        get_user=get_user,
        check_registered=check_registered,
        save_data=save_data,
    )


# =========================================================
# 거래소
# =========================================================
@bot.hybrid_command()
async def 거래소(ctx):
    if not await check_registered(ctx):
        return
    listings = world_data["market"]
    if not listings:
        await ctx.send("🏪 거래소에 등록된 장비가 없습니다.")
        return
    lines = []
    for listing_id, listing in sorted(
        listings.items(), key=lambda x: int(x[0])
    )[:30]:
        if listing.get("auction"):
            current = listing.get("highest_bid", 0) or listing.get("price", 0)
            label = f"🔨 경매 {current:,}개"
        else:
            label = f"🛒 즉시구매 {listing['price']:,}개"
        lines.append(
            f"`#{listing_id}` **{listing['item']} +{listing['enhance']}** "
            f"| {label} | 판매자 <@{listing['seller']}>"
        )
    await send_pages(ctx.channel, "🏪 **[생존자 거래소]**\n" + "\n".join(lines))


@bot.hybrid_command()
async def 판매(ctx, 아이템이름: str, 가격: int):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    if 아이템이름 not in u["inventory"]:
        await ctx.send("⚠️ 보유하지 않은 장비입니다.")
        return
    if 가격 <= 0:
        await ctx.send("⚠️ 판매 가격은 1 이상이어야 합니다.")
        return

    listing_id = str(world_data["market_next_id"])
    world_data["market_next_id"] += 1
    enhance = u["enhancements"].get(아이템이름, 0)
    options = u.get("equipment_options", {}).pop(아이템이름, None)
    u["inventory"].remove(아이템이름)
    u["enhancements"].pop(아이템이름, None)
    world_data["market"][listing_id] = {
        "seller": str(ctx.author.id),
        "item": 아이템이름,
        "enhance": enhance,
        "price": 가격,
        "options": options,
        "created": datetime.now().isoformat()
    }
    save_data()
    await ctx.send(
        f"🏪 **판매 등록 완료** `#{listing_id}`\n"
        f"{아이템이름} +{enhance} / **{가격:,}개**"
    )


@bot.hybrid_command()
async def 구매등록번호(ctx, 번호: int):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    listing_id = str(번호)
    listing = world_data["market"].get(listing_id)
    if not listing:
        await ctx.send("⚠️ 존재하지 않는 판매 등록 번호입니다.")
        return
    if listing.get("auction"):
        await ctx.send(f"⚠️ 이 매물은 경매입니다. `!입찰 {번호} 금액`을 사용하세요.")
        return
    if listing["seller"] == str(ctx.author.id):
        await ctx.send("⚠️ 자기 물건은 구매할 수 없습니다.")
        return
    if u["balance"] < listing["price"]:
        await ctx.send("⚠️ 식량이 부족합니다.")
        return
    if listing["item"] in u["inventory"]:
        await ctx.send("⚠️ 이미 같은 장비를 보유하고 있습니다.")
        return

    seller = get_user(listing["seller"])
    u["balance"] -= listing["price"]
    u["inventory"].append(listing["item"])
    u["enhancements"][listing["item"]] = listing["enhance"]
    if listing.get("options"):
        u.setdefault("equipment_options", {})[listing["item"]] = listing["options"]
    u.setdefault("market_history", []).append({"type": "구매", "item": listing["item"], "price": listing["price"], "date": datetime.now().isoformat()})
    if seller:
        seller["balance"] += listing["price"]
        seller["stats"]["earned"] += listing["price"]
        seller.setdefault("market_history", []).append({"type": "판매", "item": listing["item"], "price": listing["price"], "date": datetime.now().isoformat()})
    del world_data["market"][listing_id]
    add_season_points(u, 10)
    save_data()
    await ctx.send(
        f"🛒 **거래 완료!** {listing['item']} +{listing['enhance']} 획득."
    )


@bot.hybrid_command()
async def 판매취소(ctx, 번호: int):
    if not await check_registered(ctx):
        return
    listing_id = str(번호)
    listing = world_data["market"].get(listing_id)
    if not listing:
        await ctx.send("⚠️ 존재하지 않는 판매 등록 번호입니다.")
        return
    if listing["seller"] != str(ctx.author.id):
        await ctx.send("❌ 본인의 판매글만 취소할 수 있습니다.")
        return
    if listing.get("auction") and listing.get("highest_bidder"):
        await ctx.send("⚠️ 입찰자가 있는 경매는 취소할 수 없습니다. `!경매마감 번호`를 사용하세요.")
        return
    u = get_user(ctx.author.id)
    u["inventory"].append(listing["item"])
    u["enhancements"][listing["item"]] = listing["enhance"]
    if listing.get("options"):
        u.setdefault("equipment_options", {})[listing["item"]] = listing["options"]
    del world_data["market"][listing_id]
    save_data()
    await ctx.send(f"↩️ 판매 취소: **{listing['item']}**이 인벤토리로 돌아왔습니다.")


# =========================================================
# 파티 시스템
# =========================================================
def find_party_of(user_id):
    uid = str(user_id)
    for leader_id, party in world_data["parties"].items():
        if uid in party["members"]:
            return leader_id, party
    return None, None


@bot.hybrid_command()
async def 파티생성(ctx):
    if not await check_registered(ctx):
        return
    if find_party_of(ctx.author.id)[1]:
        await ctx.send("⚠️ 이미 파티에 소속되어 있습니다.")
        return
    uid = str(ctx.author.id)
    world_data["parties"][uid] = {"leader": uid, "members": [uid]}
    save_data()
    await ctx.send(f"👥 {ctx.author.mention}님이 파티를 생성했습니다.")


@bot.hybrid_command()
async def 파티가입(ctx, 리더: discord.Member):
    if not await check_registered(ctx):
        return
    if find_party_of(ctx.author.id)[1]:
        await ctx.send("⚠️ 이미 파티에 소속되어 있습니다.")
        return
    party = world_data["parties"].get(str(리더.id))
    if not party:
        await ctx.send("⚠️ 해당 유저가 이끄는 파티가 없습니다.")
        return
    if len(party["members"]) >= 4:
        await ctx.send("⚠️ 파티 정원이 가득 찼습니다.")
        return
    party["members"].append(str(ctx.author.id))
    save_data()
    await ctx.send(f"👥 {리더.mention}님의 파티에 가입했습니다.")


@bot.hybrid_command()
async def 파티정보(ctx):
    if not await check_registered(ctx):
        return
    leader_id, party = find_party_of(ctx.author.id)
    if not party:
        await ctx.send("⚠️ 파티에 소속되어 있지 않습니다.")
        return
    members = "\n".join(f"• <@{uid}>" for uid in party["members"])
    await ctx.send(
        f"👥 **[파티 정보]**\n리더: <@{leader_id}>\n"
        f"인원: {len(party['members'])}/4\n{members}"
    )


@bot.hybrid_command()
@commands.cooldown(1, 300, commands.BucketType.user)
async def 파티사냥(ctx):
    if not await check_registered(ctx):
        return
    leader_id, party = find_party_of(ctx.author.id)
    if not party:
        ctx.command.reset_cooldown(ctx)
        await ctx.send("⚠️ 먼저 파티를 생성하거나 가입하세요.")
        return
    if leader_id != str(ctx.author.id):
        ctx.command.reset_cooldown(ctx)
        await ctx.send("❌ 파티장만 파티 사냥을 시작할 수 있습니다.")
        return

    active = []
    total_power = 0
    for uid in party["members"]:
        member_u = get_user(uid)
        if member_u:
            active.append((uid, member_u))
            total_power += calculate_user_power(member_u)

    enemy_power = random.randint(30, 220) * max(1, len(active))
    victory = total_power >= enemy_power or random.random() < 0.30

    if victory:
        base_reward = random.randint(4000, 9000)
        for _, member_u in active:
            reward = base_reward + calculate_user_power(member_u) * 20
            member_u["balance"] += reward
            member_u["stats"]["earned"] += reward
            progress_weekly(member_u, "파티 사냥")
            add_season_points(member_u, 15)
        save_data()
        await ctx.send(
            f"👥 **[파티 사냥 승리]**\n"
            f"파티 전투력 {total_power:,} / 적 전투력 {enemy_power:,}\n"
            f"전원에게 개인별 식량 보상이 지급되었습니다."
        )
    else:
        save_data()
        await ctx.send(
            f"💀 **[파티 사냥 실패]**\n"
            f"파티 전투력 {total_power:,} / 적 전투력 {enemy_power:,}"
        )


@bot.hybrid_command()
async def 파티탈퇴(ctx):
    if not await check_registered(ctx):
        return
    leader_id, party = find_party_of(ctx.author.id)
    if not party:
        await ctx.send("⚠️ 파티에 소속되어 있지 않습니다.")
        return
    uid = str(ctx.author.id)
    if uid == leader_id:
        del world_data["parties"][leader_id]
        await ctx.send("👥 파티장이 탈퇴하여 파티가 해산되었습니다.")
    else:
        party["members"].remove(uid)
        await ctx.send("👥 파티에서 탈퇴했습니다.")
    save_data()


# =========================================================
# PVP
# =========================================================
@bot.hybrid_command(name="pvp", aliases=["PVP", "피브이피"])
@commands.cooldown(1, 120, commands.BucketType.user)
async def pvp_command(ctx, 상대: discord.Member):
    if not await check_registered(ctx):
        return
    if 상대.bot or 상대.id == ctx.author.id:
        ctx.command.reset_cooldown(ctx)
        await ctx.send("⚠️ 자기 자신이나 봇과는 대결할 수 없습니다.")
        return

    attacker = get_user(ctx.author.id)
    defender = get_user(상대.id)
    if not defender:
        ctx.command.reset_cooldown(ctx)
        await ctx.send("⚠️ 상대방이 가입하지 않았습니다.")
        return

    a_power = calculate_user_power(attacker)
    d_power = calculate_user_power(defender)
    a_score = a_power * random.uniform(0.75, 1.35)
    d_score = d_power * random.uniform(0.75, 1.35)

    if a_score >= d_score:
        winner_member, winner_u = ctx.author, attacker
        loser_member = 상대
    else:
        winner_member, winner_u = 상대, defender
        loser_member = ctx.author

    reward = random.randint(1500, 3500)
    winner_u["balance"] += reward
    winner_u["stats"]["earned"] += reward
    progress_weekly(attacker, "PVP 참여")
    progress_weekly(defender, "PVP 참여")
    add_season_points(attacker, 8)
    add_season_points(defender, 5)
    save_data()

    await ctx.send(
        f"⚔️ **[PVP 결과]**\n"
        f"{ctx.author.mention} 전투력 {a_power:,} VS {상대.mention} 전투력 {d_power:,}\n"
        f"🏆 승자: {winner_member.mention}\n"
        f"보상: 식량 **{reward:,}개**\n"
        f"패자 {loser_member.mention}의 식량은 차감되지 않습니다."
    )


# =========================================================
# 주간 퀘스트
# =========================================================
@bot.hybrid_command()
async def 주간퀘스트(ctx):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    ensure_weekly_quest(u)
    q = u["weekly_quest"]
    await ctx.send(
        f"📆 **[주간 퀘스트 {q['week']}]**\n"
        f"내용: **{q['type']} {q['target']}회**\n"
        f"진행: **{q['progress']} / {q['target']}**\n"
        f"보상: **식량 {q['reward']:,}개**\n"
        f"수령 여부: {'완료' if q['claimed'] else '미수령'}"
    )


@bot.hybrid_command()
async def 주간보상(ctx):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    q = u["weekly_quest"]
    if q["claimed"]:
        await ctx.send("⚠️ 이번 주 보상을 이미 받았습니다.")
        return
    if q["progress"] < q["target"]:
        await ctx.send("⚠️ 주간 퀘스트가 아직 완료되지 않았습니다.")
        return
    q["claimed"] = True
    u["balance"] += q["reward"]
    u["stats"]["earned"] += q["reward"]
    add_season_points(u, 80)
    save_data()
    await ctx.send(f"🎁 주간 퀘스트 보상 **{q['reward']:,}개** 지급!")


# =========================================================
# 시즌패스
# =========================================================
@bot.hybrid_command()
async def 시즌패스(ctx):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    ensure_season_pass(u)
    sp = u["season_pass"]
    lines = []
    for level, reward in SEASON_REWARDS.items():
        unlocked = sp["points"] >= reward["points"]
        claimed = level in sp["claimed_levels"]
        mark = "✅" if claimed else ("🔓" if unlocked else "🔒")
        title_text = f" + 칭호 `{reward['title']}`" if reward["title"] else ""
        lines.append(
            f"{mark} Lv.{level} | {reward['points']}P | "
            f"식량 {reward['food']:,}{title_text}"
        )
    await send_pages(
        ctx.channel,
        f"🎖️ **[{sp['season']} 시즌패스]** 현재 **{sp['points']}P**\n" +
        "\n".join(lines) +
        "\n\n수령: `!시즌보상 레벨`"
    )


@bot.hybrid_command()
async def 시즌보상(ctx, 레벨: int):
    if not await check_registered(ctx):
        return
    u = get_user(ctx.author.id)
    ensure_season_pass(u)
    sp = u["season_pass"]
    reward = SEASON_REWARDS.get(레벨)
    if not reward:
        await ctx.send("⚠️ 존재하지 않는 시즌패스 레벨입니다.")
        return
    if 레벨 in sp["claimed_levels"]:
        await ctx.send("⚠️ 이미 받은 시즌 보상입니다.")
        return
    if sp["points"] < reward["points"]:
        await ctx.send(f"⚠️ 시즌 포인트 **{reward['points']}P**가 필요합니다.")
        return

    sp["claimed_levels"].append(레벨)
    u["balance"] += reward["food"]
    u["stats"]["earned"] += reward["food"]
    if reward["title"]:
        add_title(u, reward["title"])
    save_data()
    await ctx.send(
        f"🎖️ 시즌패스 Lv.{레벨} 보상 수령!\n"
        f"식량 **{reward['food']:,}개**"
        + (f"\n칭호 **{reward['title']}** 획득!" if reward["title"] else "")
    )


# =========================================================
# 분리 모듈 명령어 등록
# =========================================================
from apocalypse_bot.commands.jobs import register_job_commands
register_job_commands(bot, get_user, check_registered, save_data)
register_status_commands(bot, get_user, check_registered, save_data)
register_condition_commands(bot, get_user, check_registered, save_data, get_max_hp)
from apocalypse_bot.commands.world_exploration import register_world_commands
register_world_commands(bot, get_user, check_registered, save_data, spend_stamina, apply_damage, get_max_hp, get_max_stamina)

# V2.0-8 퀴즈 개선 + 월드보스 개편
from apocalypse_bot.commands.daily_quiz import register_quiz_commands
register_quiz_commands(
    bot, get_user, check_registered, save_data, world_data, send_pages, add_season_points
)

# V2.0-6 관리자 통합 도구
from apocalypse_bot.commands.admin_tools import register_admin_commands
register_admin_commands(
    bot,
    get_user,
    save_data,
    send_pages,
    ITEM_DB,
    MATERIALS,
    PET_DB,
    calculate_user_power,
)


# V2.1 Apocalypse Reborn 확장
from apocalypse_bot.commands.v21_reborn import register_v21_commands
register_v21_commands(
    bot, get_user, check_registered, save_data, send_pages, world_data,
    ITEM_DB, MATERIALS, find_item, calculate_user_power, spend_stamina,
    apply_damage, get_max_hp, add_season_points,
)

# V3.0 Abaddon: 서버 침공 + 통합 도움말
from apocalypse_bot.commands.v30_invasion import register_v30_commands
register_v30_commands(
    bot, get_user, check_registered, save_data, send_pages, world_data,
    calculate_user_power, add_season_points,
)

# V3.1: 일일 퀴즈 자동 알림/스레드 + RPG 시작 온보딩
from apocalypse_bot.commands.v31_quiz_notify import register_v31_commands
register_v31_commands(
    bot, get_user, check_registered, save_data, world_data,
)


# V3.2: 통합 도감 + 서버별 설정 패널 + 초보자 튜토리얼
from apocalypse_bot.commands.v32_codex_settings_tutorial import register_v32_commands
register_v32_commands(
    bot, get_user, check_registered, save_data, world_data,
    send_pages, ITEM_DB, PET_DB,
)

# V3.3: 선택형 스토리 시즌 1 "검은 주파수"
from apocalypse_bot.commands.v33_story import register_v33_commands
register_v33_commands(
    bot, get_user, check_registered, save_data, world_data,
    get_max_hp, add_title,
)

# V3.6: 실시간 변동 암시장 + 도박 안내
from apocalypse_bot.commands.v36_gambling_market import register_v36_commands
register_v36_commands(
    bot, get_user, check_registered, save_data, world_data, progress_quest,
)

# V3.7: 도박 연출/잔액 통계 + 알바 + 희귀 코인 + 암시장 자동 알림
from apocalypse_bot.commands.v37_gambling_experience import register_v37_commands
register_v37_commands(
    bot, get_user, check_registered, save_data, world_data, progress_quest,
)

# V3.9: 통합 폐허 카지노 (블랙잭/하이로우/슬롯/다이스/바카라)
from apocalypse_bot.commands.v39_casino import register_v39_commands
register_v39_commands(
    bot, get_user, check_registered, save_data, user_data, world_data, progress_quest,
)

# V4.0: BLACK CASINO 확장 (칩/VIP/잭팟/미션/NPC/상점/럭키휠/올인)
from apocalypse_bot.commands.v40_black_casino import register_v40_casino_commands
register_v40_casino_commands(
    bot, get_user, check_registered, save_data, world_data, user_data,
)

# V4.0: 은행 + 사채 금융 시스템
from apocalypse_bot.commands.v40_finance import register_v40_finance_commands
register_v40_finance_commands(
    bot, get_user, check_registered, save_data,
)

# V4.0.3: 관리자 전용 서버 자동 꾸미기
# prefix 전용이라 Discord 글로벌 slash 100개 제한을 사용하지 않습니다.
from apocalypse_bot.commands.v403_server_builder import register_v403_server_builder
register_v403_server_builder(bot, world_data, save_data)

# V4.1: SERVER GUARD 서버 운영/제재/로그/자동관리/문의 시스템
from apocalypse_bot.commands.v410_server_management import register_v410_server_management
register_v410_server_management(bot, world_data, save_data)
print(f"[SERVER GUARD 등록 확인] 운영초기설정={bot.get_command('운영초기설정') is not None} 운영진단={bot.get_command('운영진단') is not None}", flush=True)

# V4.2: SERVER GUARD PLUS 스마트 자동 이모지/안티레이드/비상관리 확장
# prefix 전용으로 추가하여 글로벌 슬래시 100개 제한을 사용하지 않습니다.
from apocalypse_bot.commands.v411_server_guard_plus import register_v411_server_guard_plus
register_v411_server_guard_plus(bot, world_data, save_data)

# V4.2: 운영 대시보드/설정 내보내기/운영 메모/채널 보조 도구
# prefix 전용이라 Discord 글로벌 slash 100개 제한을 사용하지 않습니다.
from apocalypse_bot.commands.v420_ops_center import register_v420_ops_center
register_v420_ops_center(bot, world_data, save_data)

# V4.2.1: 셀프 역할 패널/가입자 점검/일반 편의 기능
# prefix 전용이라 Discord 글로벌 slash 100개 제한을 사용하지 않습니다.
from apocalypse_bot.commands.v421_utility_pack import register_v421_utility_pack
register_v421_utility_pack(bot, world_data, save_data)

# V4.2.2: 통합 보안센터/분리 로그/자동관리 정책/사용자 제재 기록
# prefix 전용이라 Discord 글로벌 slash 100개 제한을 사용하지 않습니다.
from apocalypse_bot.commands.v422_security_center import register_v422_security_center
register_v422_security_center(bot, world_data, save_data)

# V4.2.3: 유형별 문의·신고·건의 접수/담당자/처리상태/빠른답변 센터
# prefix 전용이라 Discord 글로벌 slash 100개 제한을 사용하지 않습니다.
from apocalypse_bot.commands.v423_intake_center import register_v423_intake_center
register_v423_intake_center(bot, world_data, save_data)

# V4.3.0: 스토리 시즌 2 "백색 방주" + 턴제 원정 전투/평판/유물
# prefix 전용 그룹으로 추가하여 Discord 글로벌 slash 100개 제한을 사용하지 않습니다.
from apocalypse_bot.commands.v430_story_expedition import register_v430_story_expedition
register_v430_story_expedition(
    bot, get_user, check_registered, save_data, calculate_user_power,
    spend_stamina, apply_damage, get_max_hp, get_max_stamina,
    add_title, add_season_points,
)

# V4.3.1: 신규 장비/경제 밸런스/유물 성장/원정 임무/스토리 편의
# prefix 전용 명령으로 추가하여 Discord 글로벌 slash 100개 제한을 사용하지 않습니다.
from apocalypse_bot.commands.v431_growth_balance import register_v431_growth_balance
register_v431_growth_balance(
    bot, get_user, check_registered, save_data, ITEM_DB, PET_DB,
)

# V4.3.2.1: 고딕 강화 연출 + Background Worker용 별도 실시간 피드 릴레이 핫픽스
# 강화 명령어는 기존 HybridCommand 인스턴스의 callback만 교체해 슬래시 개수를 늘리지 않습니다.
from apocalypse_bot.commands.v432_forge_live import register_v432_forge_live
register_v432_forge_live(
    bot, get_user, check_registered, save_data, world_data,
    find_item, get_item_slot, progress_quest, check_achievements,
)

# V5.0.1: 리뉴얼 드롭다운·슬래시 동기화·davey 음성 핫픽스
# /tts 최상위 그룹 1개만 추가하며 등록 후 전체 최상위 100개 제한을 다시 검사합니다.
from apocalypse_bot.commands.v433_voice_sanctuary import register_v433_voice_sanctuary
register_v433_voice_sanctuary(bot, world_data, save_data)

# V5.2.1: 통합 진단 센터·서버 설정 드롭다운
# prefix 전용 명령이라 글로벌 slash 최상위 명령어 수는 증가하지 않습니다.
from apocalypse_bot.commands.v521_diagnostics import register_v521_diagnostics
register_v521_diagnostics(
    bot,
    world_data,
    save_data,
    data_file=DATA_FILE,
    user_data=user_data,
)

# V6.0.0: 통합 게임 드롭다운 제어실 + 스토리 시즌 3 "종말의 왕좌"
# prefix 전용 명령으로 추가해 Discord 글로벌 slash 최상위 개수는 증가하지 않습니다.
from apocalypse_bot.commands.v600_game_center import register_v600_game_center
register_v600_game_center(
    bot, get_user, check_registered, save_data, add_title, add_season_points,
)

# V6.1.0: 채널별 규칙 25종·안전 일괄설치·중복 갱신 제어실
# prefix 전용 명령으로 추가해 Discord 글로벌 slash 최상위 개수는 증가하지 않습니다.
from apocalypse_bot.commands.v602_channel_rules import register_v602_channel_rules
register_v602_channel_rules(bot, world_data, save_data)

# V6.1.0: 채널 규칙 안전 일괄설치 + 땅파기·보물 감정 경제 루트
# prefix 전용 명령으로 추가해 Discord 글로벌 slash 최상위 개수는 증가하지 않습니다.
from apocalypse_bot.commands.v610_digging_treasure import register_v610_digging_treasure
register_v610_digging_treasure(bot, get_user, check_registered, save_data)

# V6.2.0: 독립 대화 코어·서버 기억 공방·운영진 검수·교감·오늘의 질문
# prefix 전용 명령으로 추가해 Discord 글로벌 slash 최상위 개수는 증가하지 않습니다.
from apocalypse_bot.commands.v620_dialogue_memory import register_v620_dialogue_memory
register_v620_dialogue_memory(bot, world_data, save_data)

# V7.0.0: 월드보스 실전/테스트 분리 + 안전 보상 큐 + 실제 약점·페이즈·부위 기믹
# 기존 최상위 슬래시 이름과 v6.5.4 영문 별칭을 보존하며 신규 보조 기능은 prefix 전용으로 추가합니다.
from apocalypse_bot.commands.v630_world_boss import register_v630_world_boss
register_v630_world_boss(
    bot, get_user, check_registered, save_data, world_data, calculate_user_power, add_title,
)

# V6.3.1: 알바·땅파기·채집·벌목 시네마틱 이미지 풀 + 버튼형 인카운트 12종
# 인카운트 도감은 prefix 전용이며 신규 최상위 슬래시를 추가하지 않습니다.
from apocalypse_bot.commands.v631_life_visuals import register_v631_life_visuals
register_v631_life_visuals(bot, get_user, check_registered, save_data, ITEM_DB)

from apocalypse_bot.commands.v632_life_visuals import register_v632_life_visuals
register_v632_life_visuals(bot, get_user, check_registered, save_data, ITEM_DB)

from apocalypse_bot.commands.v633_equipment_crafting import register_v633_equipment_crafting
register_v633_equipment_crafting(
    bot,
    get_user,
    check_registered,
    find_item,
    get_item_slot,
    get_item_stats,
)

# V6.3.4: 귀여운 펫 3단 진화 이미지 + !장비 통합 드롭다운/검색/페이지
from apocalypse_bot.commands.v634_pet_visuals import register_v634_pet_visuals
register_v634_pet_visuals(
    bot, get_user, PET_DB, ensure_pet_collection, get_pet_display_name, get_pet_power,
)

from apocalypse_bot.commands.v634_equipment_menu import register_v634_equipment_menu
register_v634_equipment_menu(
    bot, get_user, check_registered, ITEM_DB, TIER_ORDER, TIER_EMOJI, EQUIPMENT_SLOTS,
    find_item, get_item_slot, get_item_stats, equipment_totals,
)

# V6.3.5: 카지노 결과별 전용 이미지 + 고난도 시간형 기지 업그레이드 + 안내 최신화
from apocalypse_bot.commands.v635_casino_base import register_v635_casino_base
register_v635_casino_base(bot)

# V6.3.6: 중복 방지형 환경·기지방어·자원시장·펫 시너지·버튼 전술전투
from apocalypse_bot.commands.v636_world_combat import register_v636_world_combat
register_v636_world_combat(
    bot, get_user, check_registered, save_data, world_data, user_data,
    calculate_user_power, get_max_hp, add_title, add_season_points,
    ITEM_DB, apply_base_reaction_visual,
)

# V6.3.7: 랜덤 주기 날씨·무전/SOS·무기 내구도/개조·까마귀·돌연변이 구역·운세·자체 테스트
from apocalypse_bot.commands.v637_dynamic_events import register_v637_dynamic_events
register_v637_dynamic_events(
    bot, get_user, check_registered, save_data, world_data,
    ITEM_DB, find_item, get_item_slot, calculate_user_power,
)

# V6.3.8: 하드코어 생존 아케이드·협동 금고·동의형 고위험 결투·명령어 가이드 정리
from apocalypse_bot.commands.v638_hardcore_arcade import register_v638_hardcore_arcade
register_v638_hardcore_arcade(
    bot, get_user, check_registered, save_data, world_data,
    ITEM_DB, calculate_user_power, get_pet_power, COMMAND_GUIDE_CATEGORIES,
)

# V6.3.9: 다크존·밀수품·보급선 피버·재활용·우편·알림·명령어 분류
from apocalypse_bot.commands.v639_frontier_operations import register_v639_frontier_operations
register_v639_frontier_operations(
    bot, get_user, check_registered, save_data, world_data, user_data,
    ITEM_DB, calculate_user_power, COMMAND_GUIDE_CATEGORIES,
)

# V6.4.0: 지뢰 정산 가독성·실시간 선물 차트·반응/기억 게임·참가형 생존자 레이스·최종 명령어 분류
from apocalypse_bot.commands.v640_interactive_arcade import register_v640_interactive_arcade
register_v640_interactive_arcade(
    bot, get_user, check_registered, save_data, world_data, COMMAND_GUIDE_CATEGORIES,
)

# V6.5.0: 화면 맞춤 비주얼·기지 이미지 리마스터·28종 서버 테마·안전 강화 FX
from apocalypse_bot.commands.v641_stabilization import register_v641_stabilization
register_v641_stabilization(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
    data_file=DATA_FILE,
)

# V6.5.1: 28종 서버 리뉴얼 통합 드롭다운 · 포커/원카드/조커잡기
from apocalypse_bot.commands.v651_card_games import register_v651_card_games
register_v651_card_games(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

from apocalypse_bot.commands.v651_server_renewal import register_v651_server_renewal
register_v651_server_renewal(bot, world_data, save_data)

# V6.5.3: 영문 명령 유지 + 낚시·채집·상인·코인 전용 랜덤 이미지 갤러리
from apocalypse_bot.commands.v652_english_access import register_v652_english_access
register_v652_english_access(bot, COMMAND_GUIDE_CATEGORIES)

# V7.0.2: 다중 백업·자동 복구·명령 트랜잭션 잠금·운영 계측
from apocalypse_bot.commands.v702_stability import register_v702_stability
register_v702_stability(
    bot, world_data, user_data, save_data,
    data_file=DATA_FILE,
    create_backup=create_data_backup,
    list_backups=list_data_backups,
    validate_snapshot=validate_data_snapshot,
    runtime_state=lambda: {
        "save_count": _SAVE_COUNT,
        "last_save_at": _LAST_SAVE_AT,
        "last_backup_at": _LAST_BACKUP_AT,
        "last_save_error": _LAST_SAVE_ERROR,
        "backup_dir": DATA_BACKUP_DIR,
    },
)

# V7.1.0: 이모지 성장 루프·일일/주간 미션·누적 보상·장비 프리셋·월드보스 주간 랭킹
# 신규 기능은 prefix 전용으로 추가하고 기존 퀘스트·시즌패스·영문 명령을 유지합니다.
from apocalypse_bot.commands.v710_growth_loop import register_v710_growth_loop
register_v710_growth_loop(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
    add_title, add_season_points,
)

# V7.2.0: 통합 신규 멤버 환영·귀여운 명령 UI·선택형 테마
# 기존 prefix/slash 명령은 유지하고 !명령어/!처음 화면만 더 쉽게 연결합니다.
from apocalypse_bot.commands.v711_cute_interactions import register_v711_cute_interactions
register_v711_cute_interactions(bot, world_data, save_data, COMMAND_GUIDE_CATEGORIES)

# V7.2.1: 채널별 전용 고정 가이드 · 전체 자동 설치 · v7.2.0 협동 기능 유지
from apocalypse_bot.commands.v720_coop_cleanup import register_v720_coop_cleanup
register_v720_coop_cleanup(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V7.3.0: 스토리 시즌 4 황혼의 종착역 · 엔딩 유산 · 아바돈 1:1 칩/식량 베팅
from apocalypse_bot.commands.v730_season_story import register_v730_season_story
register_v730_season_story(
    bot, get_user, check_registered, save_data, COMMAND_GUIDE_CATEGORIES,
    add_title, add_season_points,
)

# V7.3.1: 중복 기능 읽기 전용 감사 · 스토리 순차 해금 · 관리자 점검 우회
from apocalypse_bot.commands.v731_duplicate_stability import register_v731_duplicate_stability
register_v731_duplicate_stability(
    bot, world_data, user_data, save_data, COMMAND_GUIDE_CATEGORIES,
)

# V7.5.1: 길드 통합 런타임 핫픽스 · 레이드 전술실 · 기존 길드 완전 통합 · 공동 기지 · 일일/주간 임무 · 승인형 금고 · 부위 파괴 길드 레이드
# 기존 길드 HybridCommand는 위임 방식으로 유지하고 신규 관리 기능은 prefix 전용으로 추가합니다.
from apocalypse_bot.commands.v750_guild_raid import register_v750_guild_raid
register_v750_guild_raid(
    bot, get_user, check_registered, save_data, world_data, user_data,
    COMMAND_GUIDE_CATEGORIES, calculate_user_power, add_title, add_season_points,
)

# V7.6.0: 길드 비동기 협동 파견 · 모집/역할/출발/정산/개인 보상 · 강한 중복 정산 보호
# 기존 개인 원정과 분리된 길드 금고 기반 콘텐츠이며, 신규 명령은 prefix 전용입니다.
from apocalypse_bot.commands.v760_guild_dispatch import register_v760_guild_dispatch
register_v760_guild_dispatch(
    bot, get_user, check_registered, save_data, world_data, user_data,
    COMMAND_GUIDE_CATEGORIES, calculate_user_power, add_title, add_season_points,
)

# V7.7.0: 지역 선택형 폐허 파밍 · 랜덤 인카운트 · 폐품 공방 · 전파 해독 · 일일 납품 · 생활 연구
# 공개 화면에는 획득 비율을 노출하지 않고, 연타·재접속·중복 정산을 사용자별 잠금과 고유 ID로 보호합니다.
from apocalypse_bot.commands.v770_ruin_farming import register_v770_ruin_farming
register_v770_ruin_farming(
    bot, get_user, check_registered, save_data, world_data, user_data,
    COMMAND_GUIDE_CATEGORIES, calculate_user_power, add_title, add_season_points,
)

# V7.8.0: 서버 공동 재난 · 파밍 진행 루트 연출 · 시스템점검/최신패치 테스트 핫픽스
# !테스트 상세는 이번 패치부터 직전 버전에서 추가·수정된 기능만 검사합니다.
from apocalypse_bot.commands.v780_server_disaster import register_v780_server_disaster
register_v780_server_disaster(
    bot, get_user, check_registered, save_data, world_data, user_data,
    COMMAND_GUIDE_CATEGORIES, calculate_user_power, add_title, add_season_points,
)

# V7.9.0: 운영·알림·임시 음성·우클릭·하이라이트 + 자동 공동 재난/기상/버튼 참여 확장
# 기존 문의·점검·통계·개별 알림은 삭제하지 않고 통합 진입점에서 재사용합니다.
from apocalypse_bot.commands.v790_operations_disaster import register_v790_operations_disaster
register_v790_operations_disaster(
    bot, get_user, check_registered, save_data, world_data, user_data,
    COMMAND_GUIDE_CATEGORIES, calculate_user_power, add_title, add_season_points,
)

# V8.1.0: 통합 생존 단말기 · 서버 공동 탐험 지도 · 순차 지역 개척 · 거점 · 지역 보스 · 오류 사건 조회
# v8.0 UX 계획을 흡수하되 기존 !게임/!명령어/!아바돈 대화는 삭제하거나 덮어쓰지 않습니다.
from apocalypse_bot.commands.v810_world_map_ux import register_v810_world_map_ux
register_v810_world_map_ux(
    bot, get_user, check_registered, save_data, world_data, user_data,
    COMMAND_GUIDE_CATEGORIES, calculate_user_power, add_title, add_season_points,
)

# V8.1.1: 파밍 인카운트 20종 · 우호/구조 세력 · 접촉별 동적 선택 버튼 · 이모지 프레임 이동 연출
# 기존 파밍 저장과 명령을 유지하며 최근 조우 반복을 완화하고 구버전 인덱스 저장도 복구합니다.
from apocalypse_bot.commands.v811_encounter_variety import register_v811_encounter_variety
register_v811_encounter_variety(
    bot, get_user, check_registered, save_data, world_data, user_data,
    COMMAND_GUIDE_CATEGORIES, calculate_user_power, add_title, add_season_points,
)

# V9.0.0: NPC 세력·평판·거점 교류 · 지역 무역로/호송 · 세력전쟁 · 시즌 5 세계 상태
# v8.1.1의 우호 인카운트와 v8.1.0 공동 지도를 연결하며 기존 길드·계약·상점을 삭제하지 않습니다.
from apocalypse_bot.commands.v900_faction_world_state import register_v900_faction_world_state
register_v900_faction_world_state(
    bot, get_user, check_registered, save_data, world_data, user_data,
    COMMAND_GUIDE_CATEGORIES, calculate_user_power, add_title, add_season_points,
)

# V9.2.0: 안전한 세계 시간 순환 · 공동 복구 작전 · 주간 세계 지령 · 기존 직업 전문화 · 기존 파티 기반 분대 전술
# v9.1 계획을 통합하고 기존 직업/파티/길드/재난 기능을 삭제하거나 복제하지 않습니다.
from apocalypse_bot.commands.v920_world_cycle_professions import register_v920_world_cycle_professions
register_v920_world_cycle_professions(
    bot, get_user, check_registered, save_data, world_data, user_data,
    COMMAND_GUIDE_CATEGORIES, calculate_user_power, add_title, add_season_points,
)

# V9.5.0: 단서 조합 사건 수사 · 주간 현상금 · 개인 대피소/전시실 · 협동 수사 레이드
# v9.3~v9.5 계획을 통합하며 기존 파밍·스토리·길드 레이드·파티를 삭제하거나 덮어쓰지 않습니다.
from apocalypse_bot.commands.v950_investigation_shelter_raid import register_v950_investigation_shelter_raid
register_v950_investigation_shelter_raid(
    bot, get_user, check_registered, save_data, world_data, user_data,
    COMMAND_GUIDE_CATEGORIES, calculate_user_power, add_title, add_season_points,
)

# V10.0.0: 완전 한·영 단일 언어 렌더링 · 임무 추적/도감/인연 · 주간 글로벌 탐사 · 보상 회수 센터
# 게임 상태와 보상 로직은 하나만 유지하고, 개인/서버 언어에 따라 화면만 분리합니다.
# 기존 기능·명령·데이터를 삭제하지 않으며 진행형 명령에는 이모지 이동 프레임과 실제 퍼센트 게이지를 연결합니다.
from apocalypse_bot.commands.v1000_global_survivor import register_v1000_global_survivor
register_v1000_global_survivor(
    bot, get_user, check_registered, save_data, world_data, user_data,
    COMMAND_GUIDE_CATEGORIES, calculate_user_power, add_title, add_season_points,
)

# V10.1.0: NPC 동료 생존자 · 포커 3종 · 맞고/고스톱 · 통합 패치 검수
# 기존 v6.5.1 카드 모집/예약/환불 흐름을 재사용하며 한국어와 English 화면은 선택 언어별로 분리합니다.
from apocalypse_bot.commands.v1010_companion_card_games import register_v1010_companion_card_games
register_v1010_companion_card_games(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V10.5.0: 화투 정식 배수 규칙 · 카드게임 15종 · 전 카드 아바돈 AI · 게임장/토너먼트
# 동료 실전 성장 · 생존자 연합/협동 보스 · 무료 시즌 임무를 하나의 추가 모듈로 연결합니다.
# 기존 저장과 명령은 유지하며 v1050 전용 데이터 영역만 추가합니다.
from apocalypse_bot.commands.v1050_unified_expansion import register_v1050_unified_expansion
register_v1050_unified_expansion(
    bot, get_user, check_registered, save_data, world_data, user_data,
    COMMAND_GUIDE_CATEGORIES, calculate_user_power, add_title, add_season_points,
)

# V10.6.0: 실제 턴·베팅·선택 카드게임 · 섯다 · 음수 잔액 · 무제한 정산
# v10.5의 자동 패 비교 경로를 실전 진행 세션으로 교체하며 기존 비카드 기능과 저장은 유지합니다.
from apocalypse_bot.commands.v1060_authentic_card_games import register_v1060_authentic_card_games
register_v1060_authentic_card_games(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V10.9.0: v10.7~v10.9 통합 — 신규 실전 카드 9종 · 카드룸/관전/리플레이
# 아바돈 난이도/성향 · 정보 대시보드 · 부채/재기 · 카드 리그/명예의 전당 · 최신패치 전용 검수
# 기존 카드 16종과 저장 데이터를 유지하고 전체 25종에 아바돈 초대 경로를 연결합니다.
from apocalypse_bot.commands.v1090_integrated_renewal import register_v1090_integrated_renewal
register_v1090_integrated_renewal(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V10.9.1: 카드게임 25종 상세 대시보드 · 일반/아바돈 즉시 시작 버튼
# discord.py 2.7 TextInput.label 폐기 경고 제거 · 최신 패치 범위 테스트/패치노트 갱신
from apocalypse_bot.commands.v1091_card_dashboard_hotfix import register_v1091_card_dashboard_hotfix
register_v1091_card_dashboard_hotfix(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V10.9.2: 실제 PNG 정보/지도/카드 대시보드 재적용 · 실시간 경마 · 홈페이지 ONLINE 피드 보강
# 기존 명령 이름은 유지하고 콜백만 최신 화면으로 교체하며, 경마는 음수 잔액과 무상한 판돈을 사용합니다.
from apocalypse_bot.commands.v1092_visual_status_horserace import register_v1092_visual_status_horserace
register_v1092_visual_status_horserace(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
    calculate_user_power, get_max_hp, get_max_stamina, refresh_vitals, refresh_conditions, condition_text,
    JOBS, get_pet_record, get_pet_display_name,
)

# V10.9.3: 전체 명령 UI 안정화 · Invalid emoji 전수 정리 · 명령 도감 선응답/캐시
# TextInput 폐기 경고 잔여 경로 제거 · Discord 프로필 PNG 합성 확인 · 최신 범위 검수 갱신
from apocalypse_bot.commands.v1093_command_ui_audit import register_v1093_command_ui_audit
register_v1093_command_ui_audit(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V10.9.4: 카드게임 25종 진행 메시지 PNG · 비공개 손패 PNG · 한글 폰트/줄바꿈 안정화
# 홈페이지 문장을 간단히 정리하고 최신 테스트·패치노트 범위를 v10.9.4로 교체합니다.
from apocalypse_bot.commands.v1094_image_table_patch import register_v1094_image_table_patch
register_v1094_image_table_patch(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V10.9.5: 진행 중 테이블 턴 GIF · 이미지 실패 시 임베드 복구 · 이미지 리플레이
# 카드게임/경마 공통 실시간 보드 · 공개 테이블 이미지 관전 · 최신 범위 검수
from apocalypse_bot.commands.v1095_gameplay_polish_patch import register_v1095_gameplay_polish_patch
register_v1095_gameplay_polish_patch(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V11.0.0: 게임도시 · 승자/손익/잔액 통합 결과 · 자유 레이즈 안전 한도
# 공통 경마 결승선 · ABADDON 전용 화투 48장 · 정산 장부/셔플 검증 · 테이블 장식
from apocalypse_bot.commands.v1100_game_city_overhaul import register_v1100_game_city_overhaul
register_v1100_game_city_overhaul(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V11.4.0: v11.0.1~v11.4.0 통합 — 상태 체크포인트 · 챔피언십/NPC 딜러
# 연합 대항전 · 개인 카지노 꾸미기 · 6챕터 카드 캠페인 · 일괄 이미지 자산
from apocalypse_bot.commands.v1140_championship_alliance_casino_story import register_v1140_championship_alliance_casino_story
register_v1140_championship_alliance_casino_story(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V11.4.1: 실시간 경마의 말 이모지와 움직이는 트랙 표식을 복구합니다.
# 6개 레인의 길이와 체커기 위치는 동일하며 기존 순위·배당·정산 규칙은 유지합니다.
from apocalypse_bot.commands.v1141_horse_marker_hotfix import register_v1141_horse_marker_hotfix
register_v1141_horse_marker_hotfix(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V11.4.2: 경주를 새로 만들 때마다 6마리 배당을 다시 생성합니다.
# 출발 후에는 해당 배당을 잠그고, 결과 정산은 선택 화면의 배당을 그대로 사용합니다.
from apocalypse_bot.commands.v1142_dynamic_horse_odds import register_v1142_dynamic_horse_odds
register_v1142_dynamic_horse_odds(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V11.4.3: 자동 공동 재난 알림을 전체 서버 기본 노출에서 서버별 명시적 구독 방식으로 전환합니다.
# 관리자가 지정한 채널에만 게시하며 키워드·시스템 채널 자동 선택을 제거합니다.
from apocalypse_bot.commands.v1143_disaster_optin import register_v1143_disaster_optin
register_v1143_disaster_optin(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V11.5.0: 서버 운영센터 · 서버별 알림 구독/시간 · 서버 봇 권한 검수
# 채널별 권한 프로필은 적용 전 자동 백업하며 권한·서버 설정을 복구 ID로 되돌릴 수 있습니다.
from apocalypse_bot.commands.v1150_server_operations_permissions import register_v1150_server_operations_permissions
register_v1150_server_operations_permissions(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V11.5.1: 서버 알림을 드롭다운 UI로 설정합니다.
# 종류·상태/시간·채널·역할 멘션을 선택하고 적용 전 자동 백업과 UI 복구를 제공합니다.
from apocalypse_bot.commands.v1151_alert_settings_ui import register_v1151_alert_settings_ui
register_v1151_alert_settings_ui(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V11.5.2: 새로 제작한 전통 문양 화투 48장을 모든 화투 계열 게임에 연결합니다.
# 포커 규칙과 이미지는 유지하며 월·광/열끗/띠/피 이미지 슬롯만 정확히 교체합니다.
from apocalypse_bot.commands.v1152_traditional_hwatu_refresh import register_v1152_traditional_hwatu_refresh
register_v1152_traditional_hwatu_refresh(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V11.6.0: 진행 게임 타입 보존 체크포인트 · 재시작 복구 · 실제 납부액 안전 환불
# 종료 결과 1회 보장 · 서버별 잠수 처리 · 화투 48장 전수검증 · 판정 요청 로그
from apocalypse_bot.commands.v1160_game_recovery_validation import register_v1160_game_recovery_validation
register_v1160_game_recovery_validation(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V11.9.0: v11.7~v11.9 통합 — 서버 이벤트 달력/게임 예약 · 공개 경기 중계
# 업적·화투/포커/경마/딜러/장식 수집 도감 · 최신 패치 전용 검수
from apocalypse_bot.commands.v1190_event_broadcast_collection import register_v1190_event_broadcast_collection
register_v1190_event_broadcast_collection(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V12.2.0: v12.0~v12.2 통합 — 혼돈의 축제 완전판
# 돌발 이벤트 · 파티게임 · NPC/동료 · 탐험/사업 · 예능/친목 · 꾸미기/비밀을 서버별 복구 가능한 상태로 제공합니다.
from apocalypse_bot.commands.v1220_chaos_festival_complete import register_v1220_chaos_festival_complete
register_v1220_chaos_festival_complete(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V12.2.1 / V13.2.0: Discord UI component HTTP 50035와 interaction 10062 재발 방지.
# 전송 실패 시 이모지 없는 컴포넌트로 한 번 재시도하며 돌발 이벤트 버튼은 저장 전에 선응답합니다.
from apocalypse_bot.commands.v1221_runtime_ui_hotfix import register_v1221_runtime_ui_hotfix
register_v1221_runtime_ui_hotfix(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V13.2.0: BLACK CITY 살아 있는 서버 세계 완전판.
# 도시·세력·영토·직업·제작·거래·아지트·범죄·NPC·뉴스·4주 시즌·8개 결말·공개 월드맵을 추가합니다.
from apocalypse_bot.commands.v1320_black_city_complete import register_v1320_black_city_complete
register_v1320_black_city_complete(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V13.3.0: 실제 Render 로그에서 확인된 prefix 명령/별칭 충돌을 격리하고 진단합니다.
# 기존 명령 이름을 우선 보존하며 충돌 별칭 한 개 때문에 전체 부팅이 중단되지 않습니다.
from apocalypse_bot.commands.v1330_command_registry_guard import register_v1330_command_registry_guard
register_v1330_command_registry_guard(bot, COMMAND_GUIDE_CATEGORIES)

# V15.0.0: v14.2 차원 항해 기능과 NEON ABYSS 시각·연출·문맥형 대화 통합.
# 기존 도시 저장을 유지하면서 레이어 지도, 20종 부품, Unicode 연출, 차원/크루/공격대/창작소를 추가합니다.
from apocalypse_bot.commands.v1500_neon_abyss import register_v1500_neon_abyss
register_v1500_neon_abyss(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V16.2.0: LIVING LEGENDS 완전판.
# 기존 기능과 저장을 삭제하지 않고 통합 명령어 센터, 채집센터, 개인 전설, 운명 사건, 탈것, 크루 합동기와 편의 기능을 연결합니다.
from apocalypse_bot.commands.v1620_living_legends import register_v1620_living_legends
register_v1620_living_legends(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V16.2.1: 정보 이미지 한글 폰트 깨짐 전면 보강 · 동적 채집/프로필/지원 카드 재렌더링.
# !명령어를 큰 영역 → 세부 그룹 → 기능의 3단계 구조로 축소하고 각 선택지에 짧은 설명을 제공합니다.
from apocalypse_bot.commands.v1621_visual_command_hotfix import register_v1621_visual_command_hotfix
register_v1621_visual_command_hotfix(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V16.3.1: 메인 RPG 전체 명령을 유지하면서 카지노와 비카지노 도박을 분리합니다.
# 첫 화면 카테고리 설명, 신규 입장 버튼, 정부지원금과 채집 획득·변화 표시를 추가합니다.
from apocalypse_bot.commands.v1630_core_rpg_command_city_overhaul import register_v1630_core_rpg_command_city_overhaul
register_v1630_core_rpg_command_city_overhaul(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V16.2.0: 모든 prefix 명령의 영문/ASCII 접근 경로를 최종 등록 순서에서 동기화합니다.
# 기존 별칭을 덮어쓰지 않고 충돌은 건너뛰며, 모든 명령에 최소 1개 영문 접근 경로를 보장합니다.
from apocalypse_bot.commands.v652_english_access import synchronize_all_english_aliases
synchronize_all_english_aliases(bot)

# V16.5.0: SURVIVOR CORE COMPLETE.
# English aliases are finalized first, then the command registry is rebuilt so Korean and English menus remain fully separated.
from apocalypse_bot.commands.v1650_survivor_core_complete import register_v1650_survivor_core_complete
register_v1650_survivor_core_complete(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V16.6.0: FIRST SURVIVAL & LIVE QA.
# Resumable beginner journey, visible gains/changes, state-aware buttons, live incident center, economy settlement audit and glossary.
from apocalypse_bot.commands.v1660_first_survival_live_qa import register_v1660_first_survival_live_qa
register_v1660_first_survival_live_qa(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V16.6.1: RUNTIME INTERACTION HOTFIX.
# Discord.py MISSING cog sentinel, malformed component/embed payloads and expired select edits.
from apocalypse_bot.commands.v1661_runtime_interaction_hotfix import register_v1661_runtime_interaction_hotfix
register_v1661_runtime_interaction_hotfix(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V16.7.0: LIVE OPS & POLISH.
# Button-driven operations, confirmed cleanup, runtime usage visibility, dead-link audits and mobile-safe UI polish.
from apocalypse_bot.commands.v1670_live_ops_polish import register_v1670_live_ops_polish
register_v1670_live_ops_polish(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V16.7.1: COMMAND CENTER NAMEERROR HOTFIX.
# Restores the explicitly imported select/embed/view sanitizers used by the rebuilt command hub.
from apocalypse_bot.commands.v1671_command_center_nameerror_hotfix import register_v1671_command_center_nameerror_hotfix
register_v1671_command_center_nameerror_hotfix(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V16.8.0: LONE SURVIVOR.
# Solo roguelite expedition with deterministic seeds, weekly mutations, NPC party, codex, resume and rescue.
from apocalypse_bot.commands.v1680_lone_survivor import register_v1680_lone_survivor
register_v1680_lone_survivor(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V17.0.0: BLACK SUN CREATOR ERA.
# Runtime clean sweep, bilingual creator forge, community events, Season 6 branching server story and private owner proof.
from apocalypse_bot.commands.v1700_creator_forge_season6 import register_v1700_creator_forge_season6
register_v1700_creator_forge_season6(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V17.2.0: LIVING WORLD & BROKEN OATHS.
# V17.0.1 Creator Forge group repair, V17.1 daily living world, and V17.2 NPC bonds/romance/betrayal.
from apocalypse_bot.commands.v1720_living_world_bonds import register_v1720_living_world_bonds
register_v1720_living_world_bonds(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V17.3.0: CONNECTED SURVIVAL LOOP.
# Links story, living world, solo expedition, NPC bonds, materials/crafting, city effects and survivor hub.
from apocalypse_bot.commands.v1730_connected_survival_loop import register_v1730_connected_survival_loop
register_v1730_connected_survival_loop(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V17.4.0: SYSTEM FUSION.
# Consolidates story/world/contracts/expedition/NPC/production/city into guided hubs.
from apocalypse_bot.commands.v1740_system_fusion import register_v1740_system_fusion
register_v1740_system_fusion(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V17.4.1: MOUNT VISUAL RENEWAL.
# High-definition localized mount cards, live catalog/view/ride integration, and alias-aware v17.4 audit.
from apocalypse_bot.commands.v1741_mount_visual_renewal import register_v1741_mount_visual_renewal
register_v1741_mount_visual_renewal(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V17.6.0: CHRONICLE MUSEUM & COMMUNITY SEASON.
# V17.5 museum/achievements/titles and V17.6 fair server-wide retention season.
from apocalypse_bot.commands.v1760_chronicle_museum_season import register_v1760_chronicle_museum_season
register_v1760_chronicle_museum_season(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V18.0.0: FINAL ECLIPSE DEFINITIVE EDITION.
# Runtime archive, newcomer/returner retention, daily loop, final operations, preservation and scalable ending.
from apocalypse_bot.commands.v1800_final_eclipse import register_v1800_final_eclipse
register_v1800_final_eclipse(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
    data_file=DATA_FILE,
    create_backup=create_data_backup,
    list_backups=list_data_backups,
    validate_snapshot=validate_data_snapshot,
)

# V18.0.3: CONTEXTUAL BUTTON & DROPDOWN HOTFIX.
# Removes generic global recommendations and exposes only current-feature actions.
from apocalypse_bot.commands.v1803_contextual_ui import register_v1803_contextual_ui
register_v1803_contextual_ui(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V18.0.4: DISCORD RATE LIMIT GUARD.
# Compacts Cloudflare 1015 HTML logs and defers nonessential scheduled posts during 1015/429 quarantine.
from apocalypse_bot.commands.v1804_discord_rate_guard import register_v1804_discord_rate_guard
register_v1804_discord_rate_guard(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V18.0.5: BUTTON INTERACTION WATCHDOG.
# Resolves deferred thinking states, caps contextual UI execution time and blocks duplicate clicks.
from apocalypse_bot.commands.v1805_button_interaction_watchdog import register_v1805_button_interaction_watchdog
register_v1805_button_interaction_watchdog(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
)

# V18.1.0: PUBLIC LAUNCH PACK.
# Seasonal PvP, guild-vs-guild competition, friend referrals, optional AI companion dialogue,
# website OAuth/leaderboard API, Koreanbots vote rewards, SQLite mirroring and persistent scheduler checkpoints.
from apocalypse_bot.commands.v1810_public_launch_pack import register_v1810_public_launch_pack
register_v1810_public_launch_pack(
    bot, get_user, check_registered, save_data, world_data, user_data, COMMAND_GUIDE_CATEGORIES,
    calculate_user_power, add_title,
)

# V18.1.1: PRESENCE & OWNER CONTROL.
# Forces Online presence after ready/resume and adds a private owner-only installed-guild inventory.
from apocalypse_bot.commands.v1811_presence_owner_servers import register_v1811_presence_owner_servers
register_v1811_presence_owner_servers(bot)

# V18.1.2: ABADDON SYSTEM CORE.
# Adds branded public runtime panels for Gateway/REST/CPU/RAM/uptime/hosting diagnostics.
from apocalypse_bot.commands.v1812_abaddon_system_status import register_v1812_abaddon_system_status
register_v1812_abaddon_system_status(bot)

# v18.1.3 · interaction transport guard
from apocalypse_bot.commands.v1813_interaction_transport_guard import register_v1813_interaction_transport_guard
register_v1813_interaction_transport_guard(bot)

# v18.1.4 · full UI bridge stability
# Prefix-semantics for HybridCommands, curated related dropdowns and coin-sell visibility.
from apocalypse_bot.commands.v1814_full_ui_bridge_stability import register_v1814_full_ui_bridge_stability
register_v1814_full_ui_bridge_stability(bot)

# v18.1.5 · owner-only server usage audit
# Persists per-guild feature usage for prefix/button flows and adds private owner DM reports.
from apocalypse_bot.commands.v1815_owner_usage_audit import register_v1815_owner_usage_audit
register_v1815_owner_usage_audit(bot, world_data, save_data)

# v18.2.0 · production cleanup
# Resolves legacy command-name shadowing, hides developer regression commands,
# rebuilds the public catalog and verifies SQLite usage telemetry.
from apocalypse_bot.commands.v1820_production_cleanup import register_v1820_production_cleanup
register_v1820_production_cleanup(bot)

# v18.2.1 · owner survivor registry + contextual admin UI hotfix
# Adds private owner-only survivor roster/search/count commands and suppresses gameplay
# recommendations after owner operations commands. Existing survivor data is preserved.
from apocalypse_bot.commands.v1821_owner_survivor_hotfix import register_v1821_owner_survivor_hotfix
register_v1821_owner_survivor_hotfix(bot, user_data, save_data)

# v18.2.2 · guide synchronization
# Refreshes stale gameplay/help surfaces and audits their command references at runtime.
from apocalypse_bot.commands.v1822_guide_sync import register_v1822_guide_sync
register_v1822_guide_sync(bot, COMMAND_GUIDE_CATEGORIES)

# v18.5.0 · COMMUNITY + WEB DASHBOARD
# Consolidates existing tickets/moderation/log/temp-voice systems behind a simple server settings
# surface, adds persistent button roles and authenticated web dashboard API routes.
from apocalypse_bot.commands.v1850_community_dashboard import register_v1850_community_dashboard
register_v1850_community_dashboard(bot, world_data, save_data)

from apocalypse_bot.core.slash_setup import register_grouped_slash_commands
register_grouped_slash_commands(bot)

# V5.0.2: 자동 TTS 닉네임 낭독 제거 · 채팅 내용만 재생
# V5.0.3: Edge NoAudioReceived 재시도·백오프·안정 음성·Google 대체 합성 강화

# V5.0.4: 서버 리뉴얼 5분 단계 간격·HTTP 429 감지·15분 격리·45초 안전 중단

# V5.2.0: 서버 리뉴얼 안전 자동진행·Edge 개별 음성 격리 회로

# V5.2.1: 통합 진단 센터·서버 설정 드롭다운·슬래시 동기화 상태 기록

# V6.0.0: 게임 제어실 9개 카테고리·100+ 기능·스토리 시즌 3 종말의 왕좌

# V6.1.0: 채널 규칙 25종·안전 일괄설치 + 땅파기 50회·보물 감정사 4명

# V6.2.0: 서버 기억 공방·승인 검수·아바돈 대화·교감·오늘의 질문·생존 밸런스

# v18.3.0 · UI EMERGENCY STABILITY
# discord.py 2.7 dynamic View detach/cache race guard, explicit !버튼 entry,
# owner-only full UI health audit and recoverable cache repair.
from apocalypse_bot.commands.v1830_ui_emergency_stability import register_v1830_ui_emergency_stability
register_v1830_ui_emergency_stability(bot)

# v18.5.2 · SMART COMMAND DISCOVERY
# Unknown prefix words become related-feature panels with quick buttons + dropdown instead of dead ends.
from apocalypse_bot.commands.v1852_smart_command_discovery import register_v1852_smart_command_discovery
register_v1852_smart_command_discovery(bot)

# v18.3.1 · PERSISTENT SIMPLE COMMAND HUB
# Replaces the mutation-heavy public command centre with a persistent, newcomer-friendly
# category -> group -> command flow. Rebuilds the catalogue from live registered commands.
from apocalypse_bot.commands.v1831_persistent_command_hub import register_v1831_persistent_command_hub
register_v1831_persistent_command_hub(bot)

from apocalypse_bot.commands.v1832_bilingual_persistent_hub import register_v1832_bilingual_persistent_hub
register_v1832_bilingual_persistent_hub(bot)

# v18.3.3 · OWNER ERROR DM WATCH
# Unexpected prefix/hybrid/UI/slash failures are recorded to SQLite and DM'd to
# the application owner with duplicate-alert suppression.
from apocalypse_bot.commands.v1833_owner_error_dm_watch import register_v1833_owner_error_dm_watch
register_v1833_owner_error_dm_watch(bot)

# v18.3.4 · PUBLIC SUPPORT + ONBOARDING
# 30-second sequential presence rotation, direct support contact, newcomer first-10-minutes
# flow and read-only server installation diagnostics.
from apocalypse_bot.commands.v1834_public_support_onboarding import register_v1834_public_support_onboarding
register_v1834_public_support_onboarding(bot, user_data)

# v18.5.0 final visible surfaces must run after v18.3.4 bot-info/patch-note overrides.
from apocalypse_bot.commands.v1850_community_dashboard import finalize_v1850_surfaces
finalize_v1850_surfaces(bot)

# v18.6.0 · UX / RETENTION
# Upgrades existing favorites/recent history into executable panels, adds contextual
# recommendations, personalized smart-search ordering and lightweight usage telemetry.
from apocalypse_bot.commands.v1860_ux_retention import register_v1860_ux_retention, finalize_v1860_surfaces
register_v1860_ux_retention(bot, user_data, world_data, save_data)
finalize_v1860_surfaces(bot)

# v18.9.0 · SERVER AUTOMATION / SECURITY / EXTERNAL ALERTS
# Consolidates existing welcome/autorole/poll/suggestion/schedule/security features,
# adding giveaways, free-form scheduled announcements, destructive burst watch,
# YouTube upload alerts and Twitch live alerts without duplicating mature systems.
from apocalypse_bot.commands.v1890_server_automation_security_external import (
    register_v1890_server_automation_security_external,
    finalize_v1890_surfaces,
)
register_v1890_server_automation_security_external(bot, world_data, save_data)
finalize_v1890_surfaces(bot)

# v19.0.0 · NATIVE DISCORD INTEGRATION
# Simplifies toggles to ON/OFF and bridges Discord native Polls, Scheduled Events,
# context menus, User Install commands, threads, Soundboard and native AutoMod.
from apocalypse_bot.commands.v1900_native_discord_integration import (
    register_v1900_native_discord_integration,
    finalize_v1900_surfaces,
)
register_v1900_native_discord_integration(bot, user_data, world_data, save_data)
finalize_v1900_surfaces(bot)

# v19.0.1 · BILINGUAL INVITE INTRODUCTION HOTFIX
# First server-join introduction and !봇소개 show Korean + English together.
from apocalypse_bot.commands.v1901_bilingual_invite_intro import (
    register_v1901_bilingual_invite_intro,
)
register_v1901_bilingual_invite_intro(bot)
