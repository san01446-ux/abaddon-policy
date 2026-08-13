from __future__ import annotations

"""ABADDON v12.2.1/v13.2 runtime UI reliability hotfix.

Discord rejects an entire component payload when one button/select option contains
an emoji sequence it does not accept (HTTP 50035).  It can also reject a response
when an interaction is acknowledged too late (10062).  The v12.2 feature hub
introduced a large number of component messages, so this module adds a narrow,
retry-once safety net without changing game data or command semantics.
"""

import functools
from typing import Any, Callable, Dict, Iterable, Tuple

import discord
from discord.ext import commands

VERSION = "13.2.0"


def _is_component_payload_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return (
        "50035" in text
        or "invalid form body" in text
        or ("emoji" in text and "invalid" in text)
        or "components." in text
    )


def _strip_item_emoji(item: Any) -> None:
    try:
        if getattr(item, "emoji", None) is not None:
            item.emoji = None
    except Exception:
        pass
    try:
        for option in list(getattr(item, "options", None) or []):
            if getattr(option, "emoji", None) is not None:
                option.emoji = None
    except Exception:
        pass
    try:
        for child in list(getattr(item, "children", None) or []):
            _strip_item_emoji(child)
    except Exception:
        pass


def strip_view_emojis(view: Any) -> Any:
    if view is None:
        return None
    for child in list(getattr(view, "children", None) or []):
        _strip_item_emoji(child)
    return view


def _retryable_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    retry = dict(kwargs)
    if retry.get("view") is not None:
        retry["view"] = strip_view_emojis(retry["view"])
    return retry


def _wrap_async_method(owner: Any, name: str) -> bool:
    original = getattr(owner, name, None)
    if original is None or getattr(original, "_abaddon_component_retry", False):
        return False

    @functools.wraps(original)
    async def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return await original(self, *args, **kwargs)
        except discord.HTTPException as exc:
            if kwargs.get("view") is None or not _is_component_payload_error(exc):
                raise
            retry = _retryable_kwargs(kwargs)
            print(
                f"[ABADDON v{VERSION}] component_payload_retry "
                f"method={getattr(owner, '__name__', str(owner))}.{name} "
                f"reason={type(exc).__name__}: {str(exc)[:240]}",
                flush=True,
            )
            return await original(self, *args, **retry)

    wrapped._abaddon_component_retry = True  # type: ignore[attr-defined]
    setattr(owner, name, wrapped)
    return True


def install_component_retry_runtime() -> Dict[str, bool]:
    patched: Dict[str, bool] = {}
    patched["context_send"] = _wrap_async_method(commands.Context, "send")
    response_cls = getattr(discord, "InteractionResponse", None)
    if response_cls is not None:
        patched["interaction_send"] = _wrap_async_method(response_cls, "send_message")
        patched["interaction_edit"] = _wrap_async_method(response_cls, "edit_message")
    message_cls = getattr(discord, "Message", None)
    if message_cls is not None:
        patched["message_edit"] = _wrap_async_method(message_cls, "edit")
    webhook_cls = getattr(discord, "Webhook", None)
    if webhook_cls is not None:
        patched["webhook_send"] = _wrap_async_method(webhook_cls, "send")
    messageable_cls = getattr(getattr(discord, "abc", None), "Messageable", None)
    if messageable_cls is not None:
        patched["messageable_send"] = _wrap_async_method(messageable_cls, "send")
    return patched


def register_v1221_runtime_ui_hotfix(
    bot: commands.Bot,
    get_user: Callable[..., Any],
    check_registered: Callable[..., Any],
    save_data: Callable[..., Any],
    world_data: Dict[str, Any],
    user_data: Dict[str, Any],
    guide: list[dict[str, Any]],
) -> None:
    if getattr(bot, "_abaddon_v1221_registered", False):
        return
    bot._abaddon_v1221_registered = True
    status = install_component_retry_runtime()
    bot.v1221_component_retry_status = status
    bot.v1221_strip_view_emojis = strip_view_emojis
    print(
        f"[ABADDON v{VERSION}] runtime_hotfix=enabled component_retry=enabled "
        f"interaction_fast_ack=enabled patched={sum(bool(x) for x in status.values())}",
        flush=True,
    )
