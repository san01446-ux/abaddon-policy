from __future__ import annotations

"""Pure mapping helpers for ABADDON v11.5.2 traditional-pattern hwatu art."""

from typing import MutableMapping

VERSION = "11.5.2"

# Visual slots in the 12×4 source sheet. Rules are unchanged; only art slots
# are resolved here. The two junk cards use slots 3 and 4 in most months.
def hwatu_visual_slot(
    month: int,
    category: str,
    *,
    junk: int = 0,
    uid: int = 0,
    junk_seen: MutableMapping[int, int] | None = None,
) -> int:
    month = int(month)
    category = str(category or "junk")
    uid = int(uid or 0)
    encoded_month, encoded_slot = divmod(uid, 10)
    if encoded_month == month and 1 <= encoded_slot <= 4:
        return encoded_slot
    if category.startswith("bright"):
        return 1
    if category.startswith("ribbon"):
        return 3 if month == 12 else 2
    if category.startswith("animal"):
        return 2 if month in {8, 12} else 1
    if month == 11 and int(junk) >= 2:
        return 2
    if month == 12:
        return 4
    if junk_seen is None:
        return 3 if uid % 2 == 0 else 4
    count = int(junk_seen.get(month, 0))
    junk_seen[month] = count + 1
    return 3 if count % 2 == 0 else 4


def hwatu_visual_uid(
    month: int,
    category: str,
    *,
    junk: int = 0,
    junk_seen: MutableMapping[int, int] | None = None,
) -> int:
    slot = hwatu_visual_slot(month, category, junk=junk, junk_seen=junk_seen)
    return int(month) * 10 + int(slot)
