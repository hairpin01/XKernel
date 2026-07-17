from __future__ import annotations

import re
from types import CodeType, FunctionType, MethodType, ModuleType
from typing import Any

PATCH_TARGET = "__full_load__"
PATCH_NAME = "PremiumEmojiToExtraGramEverywhere"

_PREMIUM_TAG_RE = re.compile(
    r"<(?P<tag>tg-emoji|emoji)\b(?P<attrs>[^>]*)>(?P<inner>.*?)</(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)
_EMOJI_ID_RE = re.compile(
    r"(?:emoji-id|document_id)\s*=\s*(?:\"(?P<dq>\d+)\"|'(?P<sq>\d+)'|(?P<raw>\d+))",
    re.IGNORECASE,
)

_COMMON_VALUE_ATTRS = (
    "strings",
    "STRINGS",
    "messages",
    "MESSAGES",
    "_messages",
    "ICONS",
    "icons",
    "EMOJIS",
    "emojis",
    "THEMES",
    "themes",
    "description",
)
_SKIP_ATTRS = {
    "kernel",
    "client",
    "bot_client",
    "inline_bot",
    "Button",
    "log",
    "logger",
    "config",
    "db",
    "storage",
}


def _emoji_id(attrs: str) -> str | None:
    match = _EMOJI_ID_RE.search(attrs or "")
    if not match:
        return None
    return match.group("dq") or match.group("sq") or match.group("raw")


def _clean_text(value: str) -> tuple[str, bool]:
    changed = False

    def replace(match: re.Match[str]) -> str:
        nonlocal changed
        inner, inner_changed = _clean_text(match.group("inner"))
        emoji_id = _emoji_id(match.group("attrs"))
        changed = True or inner_changed
        if not emoji_id:
            return inner
        return f'<a href="tg://emoji?id={emoji_id}">{inner}</a>'

    cleaned = value
    while True:
        next_value = _PREMIUM_TAG_RE.sub(replace, cleaned)
        if next_value == cleaned:
            break
        cleaned = next_value
    return cleaned, changed or cleaned != value


def _replace_code_consts(code: CodeType) -> tuple[CodeType, bool]:
    changed = False
    new_consts = []
    for const in code.co_consts:
        if isinstance(const, str):
            cleaned, did_change = _clean_text(const)
            new_consts.append(cleaned)
            changed = changed or did_change
        elif isinstance(const, CodeType):
            cleaned_code, did_change = _replace_code_consts(const)
            new_consts.append(cleaned_code)
            changed = changed or did_change
        else:
            new_consts.append(const)

    if not changed:
        return code, False
    return code.replace(co_consts=tuple(new_consts)), True


def _patch_function(func: Any, seen: set[int], depth: int) -> int:
    try:
        raw = getattr(func, "__func__", func)
    except Exception:
        raw = func

    if not isinstance(raw, FunctionType):
        return 0

    changes = 0
    try:
        new_code, changed = _replace_code_consts(raw.__code__)
        if changed:
            raw.__code__ = new_code
            changes += 1
    except Exception:
        pass

    try:
        closure = raw.__closure__
    except Exception:
        closure = None
    if isinstance(closure, tuple):
        for cell in closure:
            try:
                value = cell.cell_contents
            except Exception:
                continue
            changes += _patch_value(value, seen, depth + 1)

    return changes


def _patch_mapping(mapping: dict[Any, Any], seen: set[int], depth: int) -> int:
    changes = 0
    for key, value in list(mapping.items()):
        if isinstance(key, str) and key in _SKIP_ATTRS:
            continue
        replacement, nested_changes = _patch_value_with_replacement(
            value, seen, depth + 1
        )
        if nested_changes:
            changes += nested_changes
            if replacement is not value:
                mapping[key] = replacement
    return changes


def _patch_sequence(seq: Any, seen: set[int], depth: int) -> tuple[Any, int]:
    changes = 0
    items = []
    for value in seq:
        replacement, nested_changes = _patch_value_with_replacement(
            value, seen, depth + 1
        )
        items.append(replacement)
        changes += nested_changes

    if not changes:
        return seq, 0
    if isinstance(seq, tuple):
        return tuple(items), changes
    if isinstance(seq, list):
        seq[:] = items
        return seq, changes
    if isinstance(seq, set):
        seq.clear()
        seq.update(items)
        return seq, changes
    if isinstance(seq, frozenset):
        return frozenset(items), changes
    return seq, changes


def _patch_object_dict(obj: Any, seen: set[int], depth: int) -> int:
    try:
        data = vars(obj)
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0
    return _patch_mapping(data, seen, depth + 1)


def _patch_class_dict(cls: type, seen: set[int], depth: int) -> int:
    try:
        data = vars(cls)
    except Exception:
        return 0

    changes = 0
    for value in list(data.values()):
        if isinstance(value, (staticmethod, classmethod)):
            try:
                value = value.__func__
            except Exception:
                continue
        changes += _patch_value(value, seen, depth + 1)
    return changes


def _patch_value_with_replacement(
    value: Any, seen: set[int], depth: int
) -> tuple[Any, int]:
    if isinstance(value, str):
        cleaned, changed = _clean_text(value)
        return cleaned, int(changed)

    if isinstance(value, (tuple, frozenset)):
        return _patch_sequence(value, seen, depth)

    return value, _patch_value(value, seen, depth)


def _patch_value(value: Any, seen: set[int], depth: int = 0) -> int:
    if depth > 7 or value is None or isinstance(value, (str, bytes, int, float, bool)):
        return 0

    value_id = id(value)
    if value_id in seen:
        return 0
    seen.add(value_id)

    if isinstance(value, dict):
        return _patch_mapping(value, seen, depth)
    if isinstance(value, (list, set)):
        _new_value, changes = _patch_sequence(value, seen, depth)
        return changes
    if isinstance(value, (FunctionType, MethodType)):
        return _patch_function(value, seen, depth)
    if isinstance(value, ModuleType):
        return _patch_object_dict(value, seen, depth)
    if isinstance(value, type):
        return _patch_class_dict(value, seen, depth)
    if isinstance(value, CodeType):
        return 0

    changes = _patch_object_dict(value, seen, depth)
    try:
        cls = type(value)
    except Exception:
        cls = None
    if cls is not None:
        changes += _patch_class_dict(cls, seen, depth)
    return changes


def _patch_target(target: Any, seen: set[int]) -> int:
    changes = _patch_value(target, seen)

    for obj in (target, type(target)):
        for attr in _COMMON_VALUE_ATTRS:
            try:
                value = getattr(obj, attr, None)
            except Exception:
                continue
            changes += _patch_value(value, seen)
    return changes


def _iter_loaded_targets(kernel: Any):
    yielded: set[int] = set()
    for attr in ("_class_module_instances", "loaded_modules", "system_modules"):
        try:
            collection = getattr(kernel, attr, None)
        except Exception:
            collection = None
        if not isinstance(collection, dict):
            continue
        for module in collection.values():
            for candidate in (module, getattr(module, "_class_instance", None)):
                if candidate is None:
                    continue
                candidate_id = id(candidate)
                if candidate_id in yielded:
                    continue
                yielded.add(candidate_id)
                yield candidate


async def _account_has_premium(kernel: Any) -> bool:
    try:
        client = getattr(kernel, "client", None)
    except Exception:
        client = None
    if client is None:
        return False

    try:
        get_me = getattr(client, "get_me", None)
    except Exception:
        get_me = None
    if not callable(get_me):
        return False

    try:
        me = await get_me()
    except Exception:
        return False

    return bool(
        getattr(me, "premium", False)
        or getattr(me, "is_premium", False)
        or getattr(me, "telegram_premium", False)
    )


async def apply_patch(kernel, target):
    if await _account_has_premium(kernel):
        return {"converted": 0, "skipped": "telegram_premium"}

    seen: set[int] = set()
    changes = 0
    if target is not kernel:
        changes += _patch_target(target, seen)
    for loaded in _iter_loaded_targets(kernel):
        changes += _patch_target(loaded, seen)
    return {"converted": changes}
