from __future__ import annotations

import re
from types import CodeType, FunctionType, MethodType, ModuleType
from typing import Any

PATCH_TARGETS = '' # YOU HERE NAME MODULES!
PATCH_NAME = "NoPremiumEmojiEverywhere"

_TAG_NAMES = ("tg" + "-emoji", "emoji")
_PREMIUM_TAG_RE = re.compile(
    rf"<(?P<tag>{'|'.join(_TAG_NAMES)})\b[^>]*>(?P<inner>.*?)</(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)

_COMMON_VALUE_ATTRS = (
    "strings",
    "STRINGS",
    "messages",
    "MESSAGES",
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


def _clean_text(value: str) -> tuple[str, bool]:
    cleaned = value
    while True:
        next_value = _PREMIUM_TAG_RE.sub(lambda match: match.group("inner"), cleaned)
        if next_value == cleaned:
            break
        cleaned = next_value
    return cleaned, cleaned != value


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
        if isinstance(value, str):
            cleaned, changed = _clean_text(value)
            if changed:
                mapping[key] = cleaned
                changes += 1
        else:
            replacement, nested_changes = _patch_value_with_replacement(value, seen, depth + 1)
            if nested_changes:
                changes += nested_changes
                if replacement is not value:
                    mapping[key] = replacement
    return changes


def _patch_sequence(seq: Any, seen: set[int], depth: int) -> tuple[Any, int]:
    changes = 0
    items = []
    for value in seq:
        if isinstance(value, str):
            cleaned, changed = _clean_text(value)
            items.append(cleaned)
            if changed:
                changes += 1
        else:
            replacement, nested_changes = _patch_value_with_replacement(value, seen, depth + 1)
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


def _patch_value_with_replacement(value: Any, seen: set[int], depth: int) -> tuple[Any, int]:
    if isinstance(value, str):
        cleaned, changed = _clean_text(value)
        return cleaned, int(changed)

    if isinstance(value, tuple):
        return _patch_sequence(value, seen, depth)
    if isinstance(value, frozenset):
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
        return 0
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


def _patch_target(target: Any) -> int:
    seen: set[int] = set()
    if isinstance(target, ModuleType):
        changes = _patch_object_dict(target, seen, 0)
    else:
        changes = _patch_value(target, seen)

    for obj in (target, type(target)):
        for attr in _COMMON_VALUE_ATTRS:
            try:
                value = getattr(obj, attr, None)
            except Exception:
                continue
            changes += _patch_value(value, seen)
    return changes


def apply_patch(target):
    # IMPORTANT: patch only the XPatch target passed by XKernel.
    # Do not walk kernel.loaded_modules here, otherwise one target applies this
    # cleanup to every loaded module in runtime.
    return {"cleaned": _patch_target(target)}
