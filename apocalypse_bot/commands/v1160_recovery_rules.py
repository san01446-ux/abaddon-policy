from __future__ import annotations

"""Pure helpers for ABADDON v11.6.0 recovery and validation.

This module deliberately avoids discord.py imports so the serializer, refund
planner and validation logic can be tested in an offline build environment.
"""

import dataclasses
import hashlib
import importlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Sequence

VERSION = "11.6.0"
AFK_ACTIONS = ("check", "fold", "abaddon", "pause", "refund")
AFK_ALIASES = {
    "체크": "check", "자동체크": "check", "check": "check",
    "폴드": "fold", "자동폴드": "fold", "fold": "fold",
    "아바돈": "abaddon", "아바돈대행": "abaddon", "abaddon": "abaddon", "ai": "abaddon",
    "일시정지": "pause", "정지": "pause", "pause": "pause",
    "환불": "refund", "전원환불": "refund", "refund": "refund",
}

_SKIP = object()


def normalize_afk_action(value: Any, default: str = "abaddon") -> str:
    token = str(value or "").strip().casefold().replace(" ", "")
    result = AFK_ALIASES.get(token, token)
    return result if result in AFK_ACTIONS else default


def coerce_turn_seconds(value: Any, default: int = 60) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = int(default)
    return max(20, min(600, seconds))


def _class_path(value: Any) -> str:
    cls = value.__class__
    return f"{cls.__module__}:{cls.__qualname__}"


def encode_state(value: Any, *, max_depth: int = 10, _depth: int = 0) -> Any:
    """Encode common game state into a JSON-safe, type-preserving structure."""
    if _depth > max_depth:
        return {"__type__": "truncated"}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {"__type__": "bytes", "hex": value.hex()}
    if isinstance(value, tuple):
        return {"__type__": "tuple", "items": [encode_state(v, max_depth=max_depth, _depth=_depth + 1) for v in value]}
    if isinstance(value, set):
        return {"__type__": "set", "items": [encode_state(v, max_depth=max_depth, _depth=_depth + 1) for v in sorted(value, key=repr)]}
    if isinstance(value, list):
        return [encode_state(v, max_depth=max_depth, _depth=_depth + 1) for v in value]
    if isinstance(value, Mapping):
        return {
            "__type__": "mapping",
            "items": [
                [encode_state(k, max_depth=max_depth, _depth=_depth + 1), encode_state(v, max_depth=max_depth, _depth=_depth + 1)]
                for k, v in value.items()
            ],
        }
    if dataclasses.is_dataclass(value):
        return {
            "__type__": "object",
            "class": _class_path(value),
            "attrs": encode_state(dataclasses.asdict(value), max_depth=max_depth, _depth=_depth + 1),
        }
    if callable(value):
        return {"__type__": "skipped", "reason": "callable"}
    module = getattr(value.__class__, "__module__", "")
    if hasattr(value, "__dict__") and (module.startswith("apocalypse_bot.") or module == "__main__"):
        attrs: Dict[str, Any] = {}
        for key, item in vars(value).items():
            if key.startswith("_discord") or key in {"bot", "message", "get_user", "save_data", "world_data", "world_data_ref", "user_data", "lock"}:
                continue
            encoded = encode_state(item, max_depth=max_depth, _depth=_depth + 1)
            if not (isinstance(encoded, Mapping) and encoded.get("__type__") == "skipped"):
                attrs[str(key)] = encoded
        return {"__type__": "object", "class": _class_path(value), "attrs": attrs}
    return {"__type__": "skipped", "reason": f"unsupported:{_class_path(value)}"}


def _resolve_class(path: str) -> Any:
    module_name, _, qualname = str(path).partition(":")
    if not module_name or not qualname:
        raise ValueError(path)
    obj: Any = importlib.import_module(module_name)
    for token in qualname.split("."):
        obj = getattr(obj, token)
    return obj


def decode_state(value: Any) -> Any:
    if isinstance(value, list):
        return [decode_state(v) for v in value]
    if not isinstance(value, Mapping):
        return value
    kind = value.get("__type__")
    if not kind:
        return {k: decode_state(v) for k, v in value.items()}
    if kind == "bytes":
        return bytes.fromhex(str(value.get("hex", "")))
    if kind == "tuple":
        return tuple(decode_state(v) for v in value.get("items", []))
    if kind == "set":
        return set(decode_state(v) for v in value.get("items", []))
    if kind == "mapping":
        return {decode_state(pair[0]): decode_state(pair[1]) for pair in value.get("items", []) if isinstance(pair, Sequence) and len(pair) == 2}
    if kind in {"skipped", "truncated"}:
        return _SKIP
    if kind == "object":
        attrs = decode_state(value.get("attrs", {}))
        try:
            cls = _resolve_class(str(value.get("class", "")))
            if isinstance(attrs, Mapping):
                try:
                    return cls(**attrs)
                except Exception:
                    obj = cls.__new__(cls)
                    for key, item in attrs.items():
                        try:
                            object.__setattr__(obj, key, item)
                        except Exception:
                            setattr(obj, key, item)
                    return obj
        except Exception:
            return {"__class__": value.get("class"), "attrs": attrs}
    return {k: decode_state(v) for k, v in value.items()}


def apply_encoded_state(target: Any, encoded: Mapping[str, Any], *, excluded: Iterable[str] = ()) -> None:
    excluded_set = set(excluded)
    for key, raw in encoded.items():
        if key in excluded_set:
            continue
        decoded = decode_state(raw)
        if decoded is _SKIP:
            continue
        current = getattr(target, key, _SKIP)
        if isinstance(raw, Mapping) and raw.get("__type__") == "object" and current is not _SKIP and hasattr(current, "__dict__"):
            attrs_raw = raw.get("attrs", {})
            attrs_decoded = decode_state(attrs_raw)
            if isinstance(attrs_decoded, Mapping):
                for nested_key, nested_value in attrs_decoded.items():
                    if nested_value is not _SKIP:
                        try:
                            setattr(current, nested_key, nested_value)
                        except Exception:
                            pass
                continue
        try:
            setattr(target, key, decoded)
        except Exception:
            pass


def snapshot_checksum(snapshot: Mapping[str, Any]) -> str:
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=repr)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def refund_plan(reservation: Mapping[str, Any] | None, snapshot: Mapping[str, Any] | None = None) -> Dict[int, int]:
    """Return exact user refunds, preferring tracked actual payments."""
    reservation = reservation or {}
    snapshot = snapshot or {}
    paid = reservation.get("actual_paid")
    if not isinstance(paid, Mapping):
        state = snapshot.get("state", {}) if isinstance(snapshot, Mapping) else {}
        paid_raw = state.get("human_paid") if isinstance(state, Mapping) else None
        paid_decoded = decode_state(paid_raw) if paid_raw is not None else None
        paid = paid_decoded if isinstance(paid_decoded, Mapping) else None
    result: Dict[int, int] = {}
    if isinstance(paid, Mapping):
        for key, amount in paid.items():
            try:
                uid, chips = int(key), max(0, int(amount))
            except (TypeError, ValueError):
                continue
            if uid >= 0 and chips:
                result[uid] = chips
        if result:
            return result
    bet = max(0, int(reservation.get("bet", snapshot.get("bet", 0)) or 0))
    players = reservation.get("players", snapshot.get("player_ids", []))
    if isinstance(players, Sequence):
        for uid in players:
            try:
                user_id = int(uid)
            except (TypeError, ValueError):
                continue
            if user_id >= 0 and bet:
                result[user_id] = bet
    return result


def validate_hwatu_assets(manifest_path: Path, cards_dir: Path, visual_uids: Sequence[int]) -> Dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        manifest = {}
    cards = sorted(cards_dir.glob("m??_c?.png"))
    months = {month: len(manifest.get(str(month), {})) for month in range(1, 13)}
    types = {month: len(manifest.get("_types", {}).get(str(month), {})) for month in range(1, 13)}
    valid_uids = [int(uid) for uid in visual_uids]
    return {
        "cards": len(cards),
        "month_slots": months,
        "type_slots": types,
        "unique_uids": len(set(valid_uids)),
        "uid_count": len(valid_uids),
        "uid_range_ok": all(11 <= uid <= 124 and 1 <= uid % 10 <= 4 for uid in valid_uids),
        "ok": len(cards) == 48 and all(v == 4 for v in months.values()) and all(v == 4 for v in types.values()) and len(valid_uids) == 48 and len(set(valid_uids)) == 48,
    }
