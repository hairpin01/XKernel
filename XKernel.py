from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import inspect
import json
import os
import sys
import traceback
from pathlib import Path
from types import ModuleType
from typing import Any

try:
    from core.lib.utils.exceptions import CallInsecure
except Exception:  # pragma: no cover - lets docs/tools import this file outside MCUB
    class CallInsecure(RuntimeError):
        pass

from .standard import Kernel as KernelBase

_PATCH_TARGET_ATTRS = ("PATCH_TARGET", "patch_target", "target")
_PATCH_TARGETS_ATTRS = ("PATCH_TARGETS", "patch_targets", "targets")
_PATCH_APPLY_ATTRS = ("apply_patch", "patch", "apply")
_PATCH_UNAPPLY_ATTRS = ("unapply_patch", "unpatch", "unapply")
_PATCH_CONDITION_ATTRS = ("PATCH_CONDITION", "patch_condition", "condition")
_MAGIC_PRE_LOAD_TARGET = "__pre_load__"
_MAGIC_KERNEL_TARGET = "__kernel__"
_MAGIC_FULL_LOAD_TARGET = "__full_load__"
_XPATCH_STEALTH_PROTECTED_ATTRS = frozenset(
    {
        "VERSION_XKERNEL",
        "ver",
        "patch_manager",
        "xpatch",
        "patches",
        "apply_patches",
        "apply_patches_for_module",
        "enable_stealth_mode",
        "disable_stealth_mode",
        "set_xpatch_events_enabled",
        "set_xpatch_hot_reload_enabled",
        "patch_core_lib_client",
        "set_core_lib_client_branding",
        "clear_core_lib_client_patch",
        "core_lib_client_patch_status",
        "patch_core_web",
        "set_core_web_branding",
        "clear_core_web_patch",
        "core_web_patch_status",
        "set_extera_proxy_all",
        "set_extera_proxy_modules",
        "set_extera_proxy_scopes",
        "add_extera_proxy_module",
        "remove_extera_proxy_module",
        "clear_extera_proxy_modules",
        "extera_proxy_status",
        "_install_core_lib_client_hook",
        "_make_core_lib_telegram_client",
        "_install_core_web_hook",
        "_apply_core_web_branding_to_app",
        "_register_core_web_branding_route",
        "_install_core_web_branding_middleware",
        "_apply_core_web_replacements",
        "_install_extera_proxy_hook",
        "_extera_proxy_should_bypass",
        "_extera_proxy_scope_enabled",
        "_patch_extera_proxy_function",
        "_protect_xkernel_proxy_controls",
        "_patch_extera_client_proxy_class",
        "_patch_extera_proxy_imported_wrappers",
        "_apply_extera_proxy_to_loaded_modules",
        "_iter_extera_loaded_module_targets",
        "_extera_names_for_target",
        "_make_extera_client_proxy",
        "_start_xpatch_hot_reload",
        "_stop_xpatch_hot_reload",
        "_watch_xpatch_files",
        "_xpatch_base_version",
        "_xpatch_kernel_version",
        "_xpatch_events_enabled",
        "_xpatch_hot_reload_enabled",
        "_xpatch_hot_reload_interval",
        "_xpatch_hot_reload_task",
        "_xpatch_core_lib_client_patch_enabled",
        "_xpatch_core_lib_client_options",
        "_xpatch_core_lib_original_telegram_client",
        "_xpatch_core_lib_client_hook_installed",
        "_xpatch_core_web_patch_enabled",
        "_xpatch_core_web_options",
        "_xpatch_core_web_original_create_app",
        "_xpatch_core_web_hook_installed",
        "_xpatch_extera_proxy_all",
        "_xpatch_extera_proxy_modules",
        "_xpatch_extera_proxy_scopes",
        "_xpatch_extera_original_get_module_kernel",
        "_xpatch_extera_original_get_module_client",
        "_xpatch_extera_original_wrap_event_for_module",
        "_xpatch_extera_original_client_proxy_class",
        "_xpatch_extera_proxy_hook_installed",
        "_xpatch_full_load_complete",
    }
)


class XPatchPatchManager:
    """Runtime patch loader for :class:`XPatchKernel`.

    Patch files live in ``kernel.PATCHES_DIR`` (``patches/`` by default) and are
    loaded *after* normal MCUB modules. A patch is a plain Python file, not a
    regular MCUB module, so it does not register commands by itself.

    Minimal patch example::

        PATCH_TARGET = "OpenApp"
        PATCH_NAME = "OpenAppTitlePatch"

        async def apply_patch(kernel, target):
            target.title = "patched"

    Supported target declarations:
    - ``PATCH_TARGET = "OpenApp"``
    - ``PATCH_TARGETS = ["OpenApp", "OtherModule"]``
    - file name fallback ``OpenApp__something.py``

    Supported apply callbacks:
    - ``apply_patch(kernel, target)``
    - ``patch(kernel, target)``
    - ``apply(kernel, target)``

    Sync and async callbacks are both supported.
    """

    def __init__(self, kernel: Any, patches_dir: str | None = None) -> None:
        self.kernel = kernel
        self.patches_dir = patches_dir or getattr(kernel, "PATCHES_DIR", "patches")
        self.loaded_patches: dict[str, ModuleType] = {}
        self._patch_states: dict[str, tuple[int, int]] = {}
        self.applied_patches: dict[tuple[str, str], dict[str, Any]] = {}
        self.pending_patches: dict[str, list[str]] = {}
        self.pending_reasons: dict[tuple[str, str], str] = {}
        self.failed_patches: dict[tuple[str, str], str] = {}
        self.failed_tracebacks: dict[tuple[str, str], str] = {}
        self.disabled_patches: set[str] = self._load_disabled_patches()

        os.makedirs(self.patches_dir, exist_ok=True)

    async def apply_all(
        self,
        *,
        target_name: str | None = None,
        force: bool = False,
    ) -> dict[str, list[tuple[str, str]]]:
        """Load patch files and apply every patch whose target is available."""

        target_aliases = (
            self._target_aliases_for_name(target_name) if target_name else None
        )
        result: dict[str, list[tuple[str, str]]] = {
            "applied": [],
            "pending": [],
            "failed": [],
            "skipped": [],
            "disabled": [],
        }

        patches = sorted(
            self.load_patches().items(),
            key=lambda item: (
                self._patch_priority(item[1]),
                self._patch_display_name(item[1], item[0]).casefold(),
                item[0],
            ),
        )

        for patch_key, patch_module in patches:
            patch_name = self._patch_display_name(patch_module, patch_key)
            if self.is_patch_disabled(patch_key):
                result["disabled"].append((patch_name, "<disabled>"))
                continue
            if self._safe_mode_enabled():
                result["skipped"].append((patch_name, "<safe-mode>"))
                continue
            targets = self._patch_targets(patch_module)
            if not targets:
                target = "<missing-target>"
                result["failed"].append((patch_name, target))
                self.failed_patches[(patch_key, target)] = "Patch target is not declared"
                self._log(
                    "warning",
                    "[xpatch] patch %s has no PATCH_TARGET/PATCH_TARGETS",
                    patch_name,
                )
                continue

            for declared_target in targets:
                if target_aliases is not None:
                    target_norm = self._normalize(declared_target)
                    if target_norm not in target_aliases:
                        continue

                status = await self.apply_patch(
                    patch_key,
                    patch_module,
                    declared_target,
                    force=force,
                )
                result[status].append((patch_name, declared_target))

        return result

    async def apply_for_target(
        self,
        target_name: str,
        *,
        force: bool = True,
    ) -> dict[str, list[tuple[str, str]]]:
        """Apply patches that declare ``target_name`` or one of its aliases."""

        aliases = self._target_aliases_for_name(target_name)
        if force:
            self._forget_applied_targets(aliases)
        return await self.apply_all(target_name=target_name, force=False)

    async def apply_patch(
        self,
        patch_key: str,
        patch_module: ModuleType,
        target_name: str,
        *,
        force: bool = False,
    ) -> str:
        """Apply one already-loaded patch module to one target module."""

        target_norm = self._normalize(target_name)
        applied_key = (patch_key, target_norm)
        if applied_key in self.applied_patches and not force:
            return "skipped"

        patch_name = self._patch_display_name(patch_module, patch_key)
        version_error = self._patch_version_error(patch_module)
        if version_error:
            self.failed_patches[applied_key] = version_error
            self._log("warning", "[xpatch] patch %s incompatible: %s", patch_name, version_error)
            await self._emit_patch_event("xpatch:failed", patch_name, target_name, version_error)
            return "failed"

        dependency_error = self._patch_dependency_error(patch_module)
        if dependency_error:
            self._remember_pending(patch_key, target_name, dependency_error)
            self._log("debug", "[xpatch] patch %s is pending: %s", patch_name, dependency_error)
            return "pending"

        condition_status = await self._patch_condition_status(patch_module)
        if condition_status is not None:
            status, reason = condition_status
            if status == "failed":
                self.failed_patches[applied_key] = reason
                await self._emit_patch_event("xpatch:failed", patch_name, target_name, reason)
                return "failed"
            self._remember_pending(patch_key, target_name, reason)
            self._log("debug", "[xpatch] patch %s is pending: %s", patch_name, reason)
            return "pending"

        target = self.lookup_target(target_name)
        if target is None:
            self._remember_pending(patch_key, target_name, "Target is not loaded")
            self._log(
                "debug",
                "[xpatch] patch %s is pending: target %s is not loaded",
                patch_name,
                target_name,
            )
            return "pending"

        apply_callback = self._apply_callback(patch_module)
        if apply_callback is None:
            error = "Patch apply callback is not declared"
            self.failed_patches[applied_key] = error
            self._log(
                "warning",
                "[xpatch] patch %s has no apply_patch/patch/apply callback",
                patch_name,
            )
            await self._emit_patch_event("xpatch:failed", patch_name, target_name, error)
            return "failed"

        try:
            patch_result = self._call_patch_callback(apply_callback, target)
            if inspect.isawaitable(patch_result):
                patch_result = await patch_result
        except Exception as e:
            error = str(e)
            self.failed_patches[applied_key] = error
            self.failed_tracebacks[applied_key] = traceback.format_exc()
            self._log(
                "error",
                "[xpatch] patch %s failed for %s: %s",
                patch_name,
                target_name,
                e,
            )
            await self._emit_patch_event("xpatch:failed", patch_name, target_name, error)
            return "failed"

        self.applied_patches[applied_key] = {
            "patch": patch_name,
            "target": target_name,
            "result": patch_result,
        }
        self._drop_pending(patch_key, target_name)
        self.failed_patches.pop(applied_key, None)
        self._log(
            "info",
            "[xpatch] patch %s applied to %s",
            patch_name,
            target_name,
        )
        await self._emit_patch_event("xpatch:applied", patch_name, target_name, patch_result)
        return "applied"

    async def unapply_patch(self, patch_key: str, target_name: str) -> str:
        """Call one patch's unapply callback for a target, if available."""

        target_norm = self._normalize(target_name)
        applied_key = (patch_key, target_norm)
        info = self.applied_patches.get(applied_key)
        patch_module = self.loaded_patches.get(patch_key)
        if info is None or patch_module is None:
            return "skipped"

        patch_name = self._patch_display_name(patch_module, patch_key)
        callback = self._unapply_callback(patch_module)
        if callback is None:
            return "skipped"

        target = self.lookup_target(target_name)
        if target is None:
            return "pending"

        try:
            result = self._call_patch_callback(callback, target)
            if inspect.isawaitable(result):
                await result
        except Exception as e:
            self.failed_patches[applied_key] = str(e)
            self.failed_tracebacks[applied_key] = traceback.format_exc()
            self._log("error", "[xpatch] patch %s failed to unapply from %s: %s", patch_name, target_name, e)
            await self._emit_patch_event("xpatch:failed", patch_name, target_name, str(e))
            return "failed"

        self.applied_patches.pop(applied_key, None)
        self.failed_patches.pop(applied_key, None)
        self.failed_tracebacks.pop(applied_key, None)
        await self._emit_patch_event("xpatch:unapplied", patch_name, target_name, None)
        return "unapplied"

    async def unapply_patch_key(self, patch_key: str) -> dict[str, list[tuple[str, str]]]:
        """Unapply all targets for one loaded patch key."""

        result: dict[str, list[tuple[str, str]]] = {
            "unapplied": [],
            "pending": [],
            "failed": [],
            "skipped": [],
        }
        patch_module = self.loaded_patches.get(patch_key)
        patch_name = self._patch_display_name(patch_module, patch_key) if patch_module else patch_key
        targets = [target for key, target in self.applied_patches if key == patch_key]
        if not targets:
            result["skipped"].append((patch_name, "<none>"))
            return result
        for target in targets:
            status = await self.unapply_patch(patch_key, target)
            result.setdefault(status, []).append((patch_name, target))
        return result

    async def reload_changed_patches(self) -> dict[str, list[str]]:
        """Hot-reload changed patch files and re-apply available targets."""

        result: dict[str, list[str]] = {"reloaded": [], "loaded": [], "removed": [], "failed": []}
        files = {self._patch_key(path): path for path in self._iter_patch_files()}

        for stale_key in set(self.loaded_patches) - set(files):
            await self.unapply_patch_key(stale_key)
            self._forget_patch(stale_key)
            result["removed"].append(stale_key)

        changed = False
        for patch_key, file_path in files.items():
            state = self._file_state(file_path)
            known_state = self._patch_states.get(patch_key)
            if patch_key in self.loaded_patches and known_state == state:
                continue
            if patch_key in self.loaded_patches:
                await self.unapply_patch_key(patch_key)
                self._forget_patch(patch_key)
                result["reloaded"].append(patch_key)
            else:
                result["loaded"].append(patch_key)
            try:
                self.loaded_patches[patch_key] = self._load_patch_module(file_path, patch_key)
                changed = True
            except Exception as e:
                self.failed_patches[(patch_key, "<load>")] = str(e)
                self.failed_tracebacks[(patch_key, "<load>")] = traceback.format_exc()
                result["failed"].append(patch_key)
                self._log("error", "[xpatch] failed to hot-reload %s: %s", file_path, e)

        if changed:
            await self.apply_all()
        return result

    async def reload_patch_key(self, patch_key: str) -> dict[str, list[str]]:
        """Reload one patch file and run a fresh apply pass."""

        result: dict[str, list[str]] = {"reloaded": [], "failed": [], "missing": []}
        patch_key = str(patch_key)
        patch_module = self.loaded_patches.get(patch_key)
        file_path = getattr(patch_module, "__xpatch_file__", "") if patch_module else ""
        if not file_path:
            for candidate in self._iter_patch_files():
                if self._patch_key(candidate) == patch_key:
                    file_path = str(candidate)
                    break
        if not file_path or not Path(file_path).exists():
            result["missing"].append(patch_key)
            return result

        await self.unapply_patch_key(patch_key)
        self._forget_patch(patch_key)
        try:
            self.loaded_patches[patch_key] = self._load_patch_module(Path(file_path), patch_key)
        except Exception as e:
            self.failed_patches[(patch_key, "<load>")] = str(e)
            self.failed_tracebacks[(patch_key, "<load>")] = traceback.format_exc()
            result["failed"].append(patch_key)
            self._log("error", "[xpatch] failed to reload %s: %s", file_path, e)
            return result

        result["reloaded"].append(patch_key)
        await self.apply_all()
        return result

    def load_patches(self) -> dict[str, ModuleType]:
        """Discover and import patch files from ``patches_dir``."""

        seen: set[str] = set()
        for file_path in self._iter_patch_files():
            patch_key = self._patch_key(file_path)
            seen.add(patch_key)
            try:
                self.loaded_patches[patch_key] = self._load_patch_module(
                    file_path,
                    patch_key,
                )
            except Exception as e:
                target = "<load>"
                self.failed_patches[(patch_key, target)] = str(e)
                self.failed_tracebacks[(patch_key, target)] = traceback.format_exc()
                self._log("error", "[xpatch] failed to load %s: %s", file_path, e)

        for stale_key in set(self.loaded_patches) - seen:
            self.loaded_patches.pop(stale_key, None)
            self._patch_states.pop(stale_key, None)
            self.pending_patches.pop(stale_key, None)

        return dict(self.loaded_patches)

    def lookup_target(self, module_name: str) -> Any | None:
        """Find a loaded MCUB module, class-style instance, or magic target."""

        needle = self._normalize(module_name)
        if needle == _MAGIC_PRE_LOAD_TARGET:
            return self.kernel
        if needle == _MAGIC_KERNEL_TARGET:
            return self.kernel
        if needle == _MAGIC_FULL_LOAD_TARGET:
            try:
                full_load_complete = object.__getattribute__(
                    self.kernel,
                    "_xpatch_full_load_complete",
                )
            except Exception:
                full_load_complete = False
            if full_load_complete:
                return self.kernel
            return None

        for name, instance in (getattr(self.kernel, "_class_module_instances", {}) or {}).items():
            if needle in self._names_for_object(name, instance):
                return instance

        for collection_name in ("loaded_modules", "system_modules"):
            collection = getattr(self.kernel, collection_name, {}) or {}
            for name, module in collection.items():
                target = getattr(module, "_class_instance", None) or module
                names = self._names_for_object(name, target)
                names.update(self._names_for_object(getattr(module, "__name__", ""), module))
                if needle in names:
                    return target

        return None

    def _iter_patch_files(self) -> list[Path]:
        root = Path(self.patches_dir)
        if not root.exists():
            return []
        return sorted(
            path
            for path in root.rglob("*.py")
            if path.is_file() and path.name != "__init__.py"
        )

    def _load_patch_module(self, file_path: Path, patch_key: str) -> ModuleType:
        state = self._file_state(file_path)
        if self._patch_states.get(patch_key) == state and patch_key in self.loaded_patches:
            return self.loaded_patches[patch_key]

        # Patch source changed or was not loaded yet: re-import it and allow a
        # fresh application pass. Existing monkey patches are intentionally not
        # reverted; patch authors should keep patches idempotent.
        self._forget_patch(patch_key)
        sys.modules.pop(patch_key, None)

        spec = importlib.util.spec_from_file_location(patch_key, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create patch spec for {file_path}")

        module = importlib.util.module_from_spec(spec)
        module.kernel = self.kernel
        module.patch_manager = self
        module.__xpatch_file__ = str(file_path)
        sys.modules[patch_key] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(patch_key, None)
            raise
        module.__xpatch_name__ = self._patch_display_name(module, patch_key)

        self._patch_states[patch_key] = state
        return module

    def _patch_targets(self, patch_module: ModuleType) -> list[str]:
        targets: list[str] = []

        for attr_name in _PATCH_TARGET_ATTRS:
            targets.extend(self._coerce_targets(getattr(patch_module, attr_name, None)))

        for attr_name in _PATCH_TARGETS_ATTRS:
            targets.extend(self._coerce_targets(getattr(patch_module, attr_name, None)))

        if not targets:
            stem = Path(getattr(patch_module, "__xpatch_file__", "")).stem
            if "__" in stem:
                targets.append(stem.split("__", 1)[0])

        unique: list[str] = []
        seen: set[str] = set()
        for target in targets:
            norm = self._normalize(target)
            if norm and norm not in seen:
                seen.add(norm)
                unique.append(target)
        return unique

    def _apply_callback(self, patch_module: ModuleType) -> Any | None:
        for attr_name in _PATCH_APPLY_ATTRS:
            callback = getattr(patch_module, attr_name, None)
            if callable(callback):
                return callback
        return None

    def _unapply_callback(self, patch_module: ModuleType) -> Any | None:
        for attr_name in _PATCH_UNAPPLY_ATTRS:
            callback = getattr(patch_module, attr_name, None)
            if callable(callback):
                return callback
        return None

    async def _emit_patch_event(self, event_name: str, *args: Any) -> None:
        if not bool(object.__getattribute__(self.kernel, "__dict__").get("_xpatch_events_enabled", False)):
            return
        emit = getattr(self.kernel, "emit", None)
        if not callable(emit):
            return
        try:
            result = emit(event_name, *args)
            if inspect.isawaitable(result):
                await result
        except Exception as e:
            self._log("debug", "[xpatch] event %s failed: %s", event_name, e)

    def _patch_priority(self, patch_module: ModuleType) -> int:
        value = getattr(patch_module, "PATCH_PRIORITY", 100)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 100

    def _patch_depends(self, patch_module: ModuleType) -> list[str]:
        return self._coerce_targets(getattr(patch_module, "PATCH_DEPENDS", None))

    def _patch_dependency_error(self, patch_module: ModuleType) -> str | None:
        depends = {self._normalize(item) for item in self._patch_depends(patch_module)}
        if not depends:
            return None
        applied = {
            self._normalize(str(info.get("patch", "")))
            for info in self.applied_patches.values()
        }
        missing = sorted(dep for dep in depends if dep not in applied)
        if missing:
            return "Waiting for patch dependencies: " + ", ".join(missing)
        return None

    def _patch_required_xkernel(self, patch_module: ModuleType) -> tuple[int, ...] | None:
        value = getattr(patch_module, "PATCH_REQUIRES_XKERNEL", None)
        if value is None:
            return None
        return self._coerce_version_tuple(value)

    def _patch_version_error(self, patch_module: ModuleType) -> str | None:
        required = self._patch_required_xkernel(patch_module)
        if not required:
            return None
        current = self._current_xkernel_version()
        if self._version_less(current, required):
            return (
                "requires XKernel >= "
                f"{self._format_version(required)}, current is {self._format_version(current)}"
            )
        return None

    async def _patch_condition_status(self, patch_module: ModuleType) -> tuple[str, str] | None:
        condition = None
        for attr_name in _PATCH_CONDITION_ATTRS:
            if hasattr(patch_module, attr_name):
                condition = getattr(patch_module, attr_name)
                break
        if condition is None:
            return None
        try:
            if callable(condition):
                result = self._call_condition(condition)
                if inspect.isawaitable(result):
                    result = await result
            else:
                result = condition
        except Exception as e:
            return "failed", f"Patch condition failed: {e}"
        if result:
            return None
        return "pending", "Patch condition is false"

    def _call_condition(self, condition: Any) -> Any:
        try:
            signature = inspect.signature(condition)
        except (TypeError, ValueError):
            return condition(self.kernel)
        params = list(signature.parameters.values())
        if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
            return condition(self.kernel, self)
        positional = [
            p
            for p in params
            if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        if len(positional) >= 2:
            return condition(self.kernel, self)
        if len(positional) == 1:
            name = positional[0].name.lower()
            if name in {"manager", "patch_manager"}:
                return condition(self)
            return condition(self.kernel)
        kwargs: dict[str, Any] = {}
        for param in params:
            if param.kind not in (inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
                continue
            name = param.name.lower()
            if name in {"kernel", "k"}:
                kwargs[param.name] = self.kernel
            elif name in {"manager", "patch_manager"}:
                kwargs[param.name] = self
        return condition(**kwargs)

    def _current_xkernel_version(self) -> tuple[int, ...]:
        state = object.__getattribute__(self.kernel, "__dict__")
        version = state.get("_xpatch_kernel_version", state.get("VERSION_XKERNEL", (0, 0, 0)))
        return self._coerce_version_tuple(version) or (0, 0, 0)

    @staticmethod
    def _version_less(current: tuple[int, ...], required: tuple[int, ...]) -> bool:
        size = max(len(current), len(required))
        return current + (0,) * (size - len(current)) < required + (0,) * (size - len(required))

    @staticmethod
    def _format_version(version: tuple[int, ...]) -> str:
        return ".".join(str(part) for part in version)

    @staticmethod
    def _coerce_version_tuple(value: Any) -> tuple[int, ...] | None:
        if isinstance(value, str):
            parts = [part for part in value.replace(",", ".").split(".") if part.strip()]
        elif isinstance(value, (list, tuple)):
            parts = list(value)
        else:
            parts = [value]
        try:
            numbers = tuple(int(part) for part in parts)
        except (TypeError, ValueError):
            return None
        return numbers if numbers else None

    def _call_patch_callback(self, callback: Any, target: Any) -> Any:
        try:
            signature = inspect.signature(callback)
        except (TypeError, ValueError):
            return callback(self.kernel, target)

        params = list(signature.parameters.values())
        if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
            return callback(self.kernel, target)

        positional = [
            p
            for p in params
            if p.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]

        if len(positional) >= 2:
            return callback(self.kernel, target)
        if len(positional) == 1:
            name = positional[0].name.lower()
            if name in {"kernel", "k"}:
                return callback(self.kernel)
            if name in {"manager", "patch_manager"}:
                return callback(self)
            return callback(target)

        kwargs: dict[str, Any] = {}
        for param in params:
            if param.kind not in (
                inspect.Parameter.KEYWORD_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ):
                continue
            name = param.name.lower()
            if name in {"kernel", "k"}:
                kwargs[param.name] = self.kernel
            elif name in {"target", "module", "mod"}:
                kwargs[param.name] = target
            elif name in {"manager", "patch_manager"}:
                kwargs[param.name] = self
        return callback(**kwargs)

    def _target_aliases_for_name(self, target_name: str | None) -> set[str]:
        if not target_name:
            return set()

        aliases = {self._normalize(target_name)}
        target = self.lookup_target(target_name)
        if target is None:
            return aliases

        aliases.update(self._names_for_object(target_name, target))
        for name, instance in (getattr(self.kernel, "_class_module_instances", {}) or {}).items():
            if instance is target:
                aliases.update(self._names_for_object(name, instance))

        for collection_name in ("loaded_modules", "system_modules"):
            collection = getattr(self.kernel, collection_name, {}) or {}
            for name, module in collection.items():
                module_target = getattr(module, "_class_instance", None) or module
                if module_target is target:
                    aliases.update(self._names_for_object(name, module_target))
                    aliases.update(
                        self._names_for_object(getattr(module, "__name__", ""), module)
                    )

        return {alias for alias in aliases if alias}

    def _names_for_object(self, registry_name: Any, obj: Any) -> set[str]:
        names = {
            self._normalize(registry_name),
            self._normalize(getattr(obj, "name", "")),
            self._normalize(getattr(obj, "__name__", "")),
        }
        file_name = getattr(obj, "__file__", None)
        if file_name:
            names.add(self._normalize(Path(file_name).stem))
        return {name for name in names if name}

    def _forget_patch(self, patch_key: str) -> None:
        self.loaded_patches.pop(patch_key, None)
        self._patch_states.pop(patch_key, None)
        for key in list(self.applied_patches):
            if key[0] == patch_key:
                self.applied_patches.pop(key, None)
        for key in list(self.failed_patches):
            if key[0] == patch_key:
                self.failed_patches.pop(key, None)
        for key in list(self.failed_tracebacks):
            if key[0] == patch_key:
                self.failed_tracebacks.pop(key, None)
        self.pending_patches.pop(patch_key, None)
        for key in list(self.pending_reasons):
            if key[0] == patch_key:
                self.pending_reasons.pop(key, None)

    def _forget_applied_targets(self, target_aliases: set[str]) -> None:
        for applied_key in list(self.applied_patches):
            if applied_key[1] in target_aliases:
                self.applied_patches.pop(applied_key, None)

    def _disabled_state_path(self) -> Path:
        return Path(self.patches_dir) / ".xpatch_disabled.json"

    def _load_disabled_patches(self) -> set[str]:
        path = self._disabled_state_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return set()
        except Exception as e:
            self._log("warning", "[xpatch] cannot read disabled patch state: %s", e)
            return set()
        if isinstance(data, dict):
            items = data.get("disabled", [])
        else:
            items = data
        if not isinstance(items, list):
            return set()
        return {str(item) for item in items if str(item).strip()}

    def _save_disabled_patches(self) -> None:
        path = self._disabled_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"disabled": sorted(self.disabled_patches)}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def is_patch_disabled(self, patch_key: str) -> bool:
        return str(patch_key) in self.disabled_patches

    def set_patch_disabled(self, patch_key: str, disabled: bool = True) -> bool:
        patch_key = str(patch_key)
        changed = False
        if disabled and patch_key not in self.disabled_patches:
            self.disabled_patches.add(patch_key)
            changed = True
        elif not disabled and patch_key in self.disabled_patches:
            self.disabled_patches.remove(patch_key)
            changed = True
        if changed:
            self._save_disabled_patches()
        return changed

    def _safe_mode_enabled(self) -> bool:
        state = object.__getattribute__(self.kernel, "__dict__")
        if bool(state.get("_xpatch_safe_mode", False)):
            return True
        raw = os.environ.get("XKERNEL_SAFE_MODE") or os.environ.get("XPATCH_SAFE_MODE")
        if raw and str(raw).strip().casefold() not in {"0", "false", "off", "no"}:
            return True
        return any(arg in {"--xpatch-safe", "--xkernel-safe"} for arg in sys.argv)

    def _remember_pending(
        self,
        patch_key: str,
        target_name: str,
        reason: str = "Pending",
    ) -> None:
        pending = self.pending_patches.setdefault(patch_key, [])
        if target_name not in pending:
            pending.append(target_name)
        self.pending_reasons[(patch_key, self._normalize(target_name))] = reason

    def _drop_pending(self, patch_key: str, target_name: str) -> None:
        pending = self.pending_patches.get(patch_key)
        if not pending:
            return
        target_norm = self._normalize(target_name)
        self.pending_patches[patch_key] = [
            item for item in pending if self._normalize(item) != target_norm
        ]
        self.pending_reasons.pop((patch_key, target_norm), None)
        if not self.pending_patches[patch_key]:
            self.pending_patches.pop(patch_key, None)

    @staticmethod
    def _coerce_targets(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            items = [value]
        elif isinstance(value, (list, tuple, set, frozenset)):
            items = list(value)
        else:
            items = [value]

        targets: list[str] = []
        for item in items:
            text = str(item).strip()
            if text:
                targets.append(text)
        return targets

    @staticmethod
    def _normalize(value: Any) -> str:
        return str(value).strip().casefold() if value is not None else ""

    @staticmethod
    def _patch_key(file_path: Path) -> str:
        safe_stem = "".join(
            char if char.isalnum() or char == "_" else "_" for char in file_path.stem
        )
        digest = hashlib.sha1(str(file_path.resolve()).encode()).hexdigest()[:12]
        return f"_mcub_xpatch_{safe_stem}_{digest}"

    @staticmethod
    def _file_state(file_path: Path) -> tuple[int, int]:
        stat = file_path.stat()
        return stat.st_mtime_ns, stat.st_size

    @staticmethod
    def _patch_display_name(patch_module: ModuleType, fallback: str) -> str:
        return str(
            getattr(
                patch_module,
                "PATCH_NAME",
                getattr(patch_module, "name", getattr(patch_module, "__name__", fallback)),
            )
        )

    def _log(self, level: str, message: str, *args: Any) -> None:
        logger = getattr(self.kernel, "logger", None)
        log_method = getattr(logger, level, None)
        if callable(log_method):
            log_method(message, *args)


class XPatchKernel(KernelBase):
    """MCUB kernel variant with a small runtime patch manager."""

    PATCHES_DIR = "patches"

    def __getattribute__(self, name: str) -> Any:
        if name in _XPATCH_STEALTH_PROTECTED_ATTRS:
            state = object.__getattribute__(self, "__dict__")
            if state.get("_xpatch_stealth_mode", False):
                raise CallInsecure(
                    f"Access to protected XKernel attribute {name!r} is denied "
                    "in stealth mode"
                )
        return super().__getattribute__(name)

    def _xpatch_manager(self) -> XPatchPatchManager:
        return object.__getattribute__(self, "patch_manager")

    @staticmethod
    def _detect_xpatch_safe_mode() -> bool:
        raw = os.environ.get("XKERNEL_SAFE_MODE") or os.environ.get("XPATCH_SAFE_MODE")
        if raw and str(raw).strip().casefold() not in {"0", "false", "off", "no"}:
            return True
        return any(arg in {"--xpatch-safe", "--xkernel-safe"} for arg in sys.argv)

    def xpatch_safe_mode_enabled(self) -> bool:
        """Return True when patch application is disabled for recovery boot."""

        return bool(object.__getattribute__(self, "__dict__").get("_xpatch_safe_mode", False))

    def __init__(self) -> None:
        super().__init__()

        self._xpatch_base_version = self.VERSION
        self._xpatch_kernel_version = (0, 0, 7)
        self._xpatch_stealth_mode = False
        self._xpatch_safe_mode = self._detect_xpatch_safe_mode()
        self._xpatch_events_enabled = False
        self._xpatch_hot_reload_enabled = False
        self._xpatch_hot_reload_interval = 2.0
        self._xpatch_core_lib_client_patch_enabled = False
        self._xpatch_core_lib_client_options: dict[str, Any] = {}
        self._xpatch_core_lib_original_telegram_client = None
        self._xpatch_core_lib_client_hook_installed = False
        self._xpatch_core_web_patch_enabled = False
        self._xpatch_core_web_options: dict[str, Any] = {}
        self._xpatch_core_web_original_create_app = None
        self._xpatch_core_web_hook_installed = False
        self._xpatch_extera_proxy_all = False
        self._xpatch_extera_proxy_modules: set[str] = set()
        self._xpatch_extera_proxy_scopes: set[str] = {"kernel"}
        self._xpatch_extera_original_get_module_kernel = None
        self._xpatch_extera_original_get_module_client = None
        self._xpatch_extera_original_wrap_event_for_module = None
        self._xpatch_extera_original_client_proxy_class = None
        self._xpatch_extera_proxy_hook_installed = False
        self.ver = f"{self.VERSION}.XPatch"
        self.VERSION = self.ver
        self.VERSION_XKERNEL = (0, 0, 7)
        self._xpatch_full_load_complete = False
        self._xpatch_retry_task = None
        self._xpatch_hot_reload_task = None

        self.patch_manager = XPatchPatchManager(self)
        self.xpatch = self.patch_manager
        self.patches = self.patch_manager
        self._install_extera_proxy_hook()
        if not self._xpatch_safe_mode:
            self._install_xpatch_loader_hooks()

    def setup_directories(self) -> None:
        super().setup_directories()
        os.makedirs(self.PATCHES_DIR, exist_ok=True)

    async def apply_patches(
        self,
        target_name: str | None = None,
        *,
        force: bool = False,
    ) -> dict[str, list[tuple[str, str]]]:
        """Public helper for manually applying XPatch patches."""

        return await self._xpatch_manager().apply_all(target_name=target_name, force=force)

    async def apply_patches_for_module(
        self,
        module_name: str,
        *,
        force: bool = True,
    ) -> dict[str, list[tuple[str, str]]]:
        """Re-apply XPatch patches for one loaded module."""

        return await self._xpatch_manager().apply_for_target(module_name, force=force)

    def enable_stealth_mode(self) -> None:
        """Hide XPatch-specific runtime markers while keeping patch hooks active."""

        base_version = str(object.__getattribute__(self, "_xpatch_base_version"))
        if base_version.endswith(".XPatch"):
            base_version = base_version[: -len(".XPatch")]

        self.VERSION = base_version
        self.CORE_NAME = "standard"

        state = object.__getattribute__(self, "__dict__")
        for attr in ("VERSION_XKERNEL", "ver"):
            state.pop(attr, None)
        object.__setattr__(self, "_xpatch_stealth_mode", True)

    def disable_stealth_mode(self) -> None:
        """Restore XPatch-specific runtime markers after stealth mode."""

        object.__setattr__(self, "_xpatch_stealth_mode", False)
        base_version = str(object.__getattribute__(self, "_xpatch_base_version"))
        if base_version.endswith(".XPatch"):
            base_version = base_version[: -len(".XPatch")]

        self.ver = f"{base_version}.XPatch"
        self.VERSION = self.ver
        self.VERSION_XKERNEL = object.__getattribute__(self, "_xpatch_kernel_version")
        self.CORE_NAME = "XPatchKernel"

    def patch_core_lib_client(
        self,
        *,
        enabled: bool = True,
        device_model: str | None = None,
        system_version: str | None = None,
        app_version: str | None = None,
        lang_code: str | None = None,
        system_lang_code: str | None = None,
    ) -> dict[str, Any]:
        """Patch ``core.lib.base.client`` Telegram identity kwargs at runtime.

        MCUB builds the user ``TelegramClient`` inside
        ``core/lib/base/client.py``. This API replaces only that module's
        ``TelegramClient`` constructor reference and overrides selected
        identity fields before the real Telethon client is created.
        """

        options = {
            "device_model": device_model,
            "system_version": system_version,
            "app_version": app_version,
            "lang_code": lang_code,
            "system_lang_code": system_lang_code,
        }
        normalized = {
            key: str(value)
            for key, value in options.items()
            if value is not None and str(value) != ""
        }
        object.__setattr__(self, "_xpatch_core_lib_client_patch_enabled", bool(enabled))
        object.__setattr__(self, "_xpatch_core_lib_client_options", normalized)
        object.__getattribute__(self, "_install_core_lib_client_hook")()
        return object.__getattribute__(self, "core_lib_client_patch_status")()

    def set_core_lib_client_branding(self, **options: Any) -> dict[str, Any]:
        """Alias for :meth:`patch_core_lib_client`."""

        return self.patch_core_lib_client(**options)

    def clear_core_lib_client_patch(self) -> dict[str, Any]:
        """Disable the core-lib client identity patch and restore the constructor."""

        object.__setattr__(self, "_xpatch_core_lib_client_patch_enabled", False)
        object.__setattr__(self, "_xpatch_core_lib_client_options", {})
        object.__getattribute__(self, "_install_core_lib_client_hook")()
        return object.__getattribute__(self, "core_lib_client_patch_status")()

    def core_lib_client_patch_status(self) -> dict[str, Any]:
        """Return current ``core.lib.base.client`` patch state."""

        return {
            "enabled": bool(
                object.__getattribute__(self, "_xpatch_core_lib_client_patch_enabled")
            ),
            "options": dict(
                object.__getattribute__(self, "_xpatch_core_lib_client_options")
            ),
            "hook_installed": bool(
                object.__getattribute__(self, "_xpatch_core_lib_client_hook_installed")
            ),
        }

    def patch_core_web(
        self,
        *,
        enabled: bool = True,
        app_name: str | None = None,
        title: str | None = None,
        replacements: dict[str, str] | None = None,
        expose_api: bool = True,
    ) -> dict[str, Any]:
        """Patch ``core.web`` app creation with branding metadata and rewrites.

        The web patch wraps ``core.web.app.create_app``. Every new aiohttp app
        receives branding data in app state/Jinja globals, an optional status API,
        and a lightweight HTML/JS/CSS text replacement middleware.
        """

        normalized_replacements: dict[str, str] = {}
        if app_name:
            normalized_replacements["MCUB"] = str(app_name)
        if title:
            normalized_replacements["MCUB - Setup"] = str(title)
        elif app_name:
            normalized_replacements["MCUB - Setup"] = f"{app_name} - Setup"
        if replacements:
            normalized_replacements.update(
                {
                    str(source): str(target)
                    for source, target in replacements.items()
                    if str(source)
                }
            )

        options = {
            "app_name": str(app_name) if app_name else None,
            "title": str(title) if title else None,
            "replacements": normalized_replacements,
            "expose_api": bool(expose_api),
        }
        object.__setattr__(self, "_xpatch_core_web_patch_enabled", bool(enabled))
        object.__setattr__(self, "_xpatch_core_web_options", options)
        object.__getattribute__(self, "_install_core_web_hook")()
        return object.__getattribute__(self, "core_web_patch_status")()

    def set_core_web_branding(self, **options: Any) -> dict[str, Any]:
        """Alias for :meth:`patch_core_web`."""

        return self.patch_core_web(**options)

    def clear_core_web_patch(self) -> dict[str, Any]:
        """Disable the core.web patch and restore ``create_app`` when possible."""

        object.__setattr__(self, "_xpatch_core_web_patch_enabled", False)
        object.__setattr__(self, "_xpatch_core_web_options", {})
        object.__getattribute__(self, "_install_core_web_hook")()
        return object.__getattribute__(self, "core_web_patch_status")()

    def core_web_patch_status(self) -> dict[str, Any]:
        """Return current ``core.web`` patch state."""

        return {
            "enabled": bool(object.__getattribute__(self, "_xpatch_core_web_patch_enabled")),
            "options": dict(object.__getattribute__(self, "_xpatch_core_web_options")),
            "hook_installed": bool(
                object.__getattribute__(self, "_xpatch_core_web_hook_installed")
            ),
        }

    def _install_core_lib_client_hook(self) -> None:
        try:
            from core.lib.base import client as client_module
        except Exception as e:
            logger = getattr(self, "logger", None)
            log_method = getattr(logger, "debug", None)
            if callable(log_method):
                log_method("[xpatch] core-lib client hook unavailable: %s", e)
            return

        current = getattr(client_module, "TelegramClient", None)
        if current is None:
            return

        original = object.__getattribute__(self, "_xpatch_core_lib_original_telegram_client")
        if original is None:
            original = getattr(current, "__xkernel_original__", current)
            object.__setattr__(self, "_xpatch_core_lib_original_telegram_client", original)

        enabled = bool(object.__getattribute__(self, "_xpatch_core_lib_client_patch_enabled"))
        if not enabled:
            if getattr(current, "__xkernel_core_lib_client_patch__", False):
                setattr(client_module, "TelegramClient", original)
            object.__setattr__(self, "_xpatch_core_lib_client_hook_installed", False)
            return

        patched = object.__getattribute__(self, "_make_core_lib_telegram_client")(original)
        setattr(client_module, "TelegramClient", patched)
        object.__setattr__(self, "_xpatch_core_lib_client_hook_installed", True)

    def _make_core_lib_telegram_client(self, original: Any) -> Any:
        def xkernel_telegram_client(*args: Any, **kwargs: Any) -> Any:
            if object.__getattribute__(self, "_xpatch_core_lib_client_patch_enabled"):
                kwargs.update(
                    object.__getattribute__(self, "_xpatch_core_lib_client_options")
                )
            return original(*args, **kwargs)

        xkernel_telegram_client.__name__ = getattr(original, "__name__", "TelegramClient")
        xkernel_telegram_client.__qualname__ = getattr(
            original, "__qualname__", xkernel_telegram_client.__name__
        )
        xkernel_telegram_client.__doc__ = getattr(original, "__doc__", None)
        xkernel_telegram_client.__xkernel_original__ = original
        xkernel_telegram_client.__xkernel_core_lib_client_patch__ = True
        return xkernel_telegram_client

    def _install_core_web_hook(self) -> None:
        try:
            from core.web import app as web_app_module
        except Exception as e:
            logger = getattr(self, "logger", None)
            log_method = getattr(logger, "debug", None)
            if callable(log_method):
                log_method("[xpatch] core.web hook unavailable: %s", e)
            return

        current = getattr(web_app_module, "create_app", None)
        if current is None:
            return

        original = object.__getattribute__(self, "_xpatch_core_web_original_create_app")
        if original is None:
            original = getattr(current, "__xkernel_original__", current)
            object.__setattr__(self, "_xpatch_core_web_original_create_app", original)

        enabled = bool(object.__getattribute__(self, "_xpatch_core_web_patch_enabled"))
        if not enabled:
            if getattr(current, "__xkernel_core_web_patch__", False):
                setattr(web_app_module, "create_app", original)
            object.__setattr__(self, "_xpatch_core_web_hook_installed", False)
            return

        def xkernel_create_app(*args: Any, **kwargs: Any) -> Any:
            app = original(*args, **kwargs)
            object.__getattribute__(self, "_apply_core_web_branding_to_app")(app)
            return app

        xkernel_create_app.__name__ = getattr(original, "__name__", "create_app")
        xkernel_create_app.__qualname__ = getattr(
            original, "__qualname__", xkernel_create_app.__name__
        )
        xkernel_create_app.__doc__ = getattr(original, "__doc__", None)
        xkernel_create_app.__xkernel_original__ = original
        xkernel_create_app.__xkernel_core_web_patch__ = True
        setattr(web_app_module, "create_app", xkernel_create_app)
        object.__setattr__(self, "_xpatch_core_web_hook_installed", True)

    def _apply_core_web_branding_to_app(self, app: Any) -> None:
        if not object.__getattribute__(self, "_xpatch_core_web_patch_enabled"):
            return

        options = dict(object.__getattribute__(self, "_xpatch_core_web_options"))
        try:
            app["xkernel_web_branding"] = options
            app["xkernel_branding"] = options
        except Exception:
            return

        try:
            import aiohttp_jinja2

            env = aiohttp_jinja2.get_env(app)
            env.globals["xkernel_branding"] = options
            if options.get("app_name"):
                env.globals["app_name"] = options["app_name"]
            if options.get("title"):
                env.globals["page_title"] = options["title"]
        except Exception:
            pass

        if options.get("expose_api", True):
            object.__getattribute__(self, "_register_core_web_branding_route")(app)
        if options.get("replacements"):
            object.__getattribute__(self, "_install_core_web_branding_middleware")(app)

    def _register_core_web_branding_route(self, app: Any) -> None:
        try:
            from aiohttp import web
        except Exception:
            return

        async def xkernel_branding(_request: Any) -> Any:
            return web.json_response(object.__getattribute__(self, "core_web_patch_status")())

        try:
            app.router.add_get("/api/xkernel/branding", xkernel_branding)
        except Exception:
            pass

    def _install_core_web_branding_middleware(self, app: Any) -> None:
        try:
            from aiohttp import web
        except Exception:
            return

        if app.get("xkernel_branding_middleware_installed"):
            return

        @web.middleware
        async def xkernel_branding_middleware(request: Any, handler: Any) -> Any:
            response = await handler(request)
            content_type = str(getattr(response, "content_type", "") or "")
            if content_type not in {"text/html", "text/css", "application/javascript", "text/javascript"}:
                return response

            text = None
            try:
                text = response.text
            except Exception:
                body = getattr(response, "body", None)
                if body is not None:
                    try:
                        text = body.decode(getattr(response, "charset", None) or "utf-8")
                    except Exception:
                        text = None
            if not text:
                return response

            rewritten = object.__getattribute__(self, "_apply_core_web_replacements")(text)
            if rewritten == text:
                return response

            headers = getattr(response, "headers", {}).copy()
            headers.pop("Content-Length", None)
            headers.pop("Content-Type", None)
            response_kwargs = {
                "text": rewritten,
                "status": getattr(response, "status", 200),
                "headers": headers,
                "content_type": content_type,
            }
            charset = getattr(response, "charset", None)
            if charset:
                response_kwargs["charset"] = charset
            return web.Response(
                **response_kwargs,
            )

        try:
            app.middlewares.append(xkernel_branding_middleware)
            app["xkernel_branding_middleware_installed"] = True
        except Exception:
            pass

    def _apply_core_web_replacements(self, text: str) -> str:
        options = object.__getattribute__(self, "_xpatch_core_web_options")
        replacements = dict(options.get("replacements") or {})
        for source, target in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
            text = text.replace(source, target)
        return text

    def set_extera_proxy_all(self, enabled: bool) -> None:
        """Force raw kernel instead of ModuleKernelProxy for all user modules."""

        object.__setattr__(self, "_xpatch_extera_proxy_all", bool(enabled))
        object.__getattribute__(self, "_install_extera_proxy_hook")()
        object.__getattribute__(self, "_apply_extera_proxy_to_loaded_modules")()

    def set_extera_proxy_modules(self, modules: Any) -> None:
        """Set module allowlist for ExteraProxy raw-kernel access."""

        normalized = {
            self._normalize_extera_module_name(item)
            for item in self._coerce_extera_modules(modules)
        }
        normalized.discard("")
        object.__setattr__(self, "_xpatch_extera_proxy_modules", normalized)
        object.__getattribute__(self, "_install_extera_proxy_hook")()
        object.__getattribute__(self, "_apply_extera_proxy_to_loaded_modules")()

    def set_extera_proxy_scopes(self, scopes: Any) -> None:
        """Choose which proxies ExteraProxy disables: kernel, client, event."""

        normalized = {
            str(item).strip().casefold()
            for item in self._coerce_extera_modules(scopes)
        }
        allowed = {"kernel", "client", "event", "root"}
        normalized = {item for item in normalized if item in allowed}
        if "root" in normalized or {"kernel", "client", "event"}.issubset(normalized):
            normalized = {"root"}
        if not normalized:
            normalized = {"kernel"}
        object.__setattr__(self, "_xpatch_extera_proxy_scopes", normalized)
        object.__getattribute__(self, "_install_extera_proxy_hook")()
        object.__getattribute__(self, "_apply_extera_proxy_to_loaded_modules")()

    def add_extera_proxy_module(self, module_name: str) -> set[str]:
        modules = set(object.__getattribute__(self, "_xpatch_extera_proxy_modules"))
        normalized = self._normalize_extera_module_name(module_name)
        if normalized:
            modules.add(normalized)
        object.__setattr__(self, "_xpatch_extera_proxy_modules", modules)
        object.__getattribute__(self, "_install_extera_proxy_hook")()
        object.__getattribute__(self, "_apply_extera_proxy_to_loaded_modules")()
        return set(modules)

    def remove_extera_proxy_module(self, module_name: str) -> set[str]:
        modules = set(object.__getattribute__(self, "_xpatch_extera_proxy_modules"))
        modules.discard(self._normalize_extera_module_name(module_name))
        object.__setattr__(self, "_xpatch_extera_proxy_modules", modules)
        object.__getattribute__(self, "_apply_extera_proxy_to_loaded_modules")()
        return set(modules)

    def clear_extera_proxy_modules(self) -> None:
        object.__setattr__(self, "_xpatch_extera_proxy_modules", set())
        object.__getattribute__(self, "_apply_extera_proxy_to_loaded_modules")()

    def extera_proxy_status(self) -> dict[str, Any]:
        modules = sorted(object.__getattribute__(self, "_xpatch_extera_proxy_modules"))
        return {
            "all": bool(object.__getattribute__(self, "_xpatch_extera_proxy_all")),
            "modules": modules,
            "count": len(modules),
            "scopes": sorted(object.__getattribute__(self, "_xpatch_extera_proxy_scopes")),
            "hook_installed": bool(
                object.__getattribute__(self, "_xpatch_extera_proxy_hook_installed")
            ),
        }

    def _install_extera_proxy_hook(self) -> None:
        try:
            from core.lib.loader import kernel_proxy as kernel_proxy_module
        except Exception as e:
            logger = getattr(self, "logger", None)
            log_method = getattr(logger, "debug", None)
            if callable(log_method):
                log_method("[xpatch] ExteraProxy hook unavailable: %s", e)
            return

        self._protect_xkernel_proxy_controls(kernel_proxy_module)
        self._patch_extera_proxy_function(
            kernel_proxy_module,
            "get_module_kernel",
            "_xpatch_extera_original_get_module_kernel",
            self._make_extera_get_module_kernel,
        )
        self._patch_extera_proxy_function(
            kernel_proxy_module,
            "get_module_client",
            "_xpatch_extera_original_get_module_client",
            self._make_extera_get_module_client,
        )
        self._patch_extera_proxy_function(
            kernel_proxy_module,
            "wrap_event_for_module",
            "_xpatch_extera_original_wrap_event_for_module",
            self._make_extera_wrap_event_for_module,
        )
        self._patch_extera_client_proxy_class(kernel_proxy_module)
        self._patch_extera_proxy_imported_wrappers(kernel_proxy_module)
        object.__setattr__(self, "_xpatch_extera_proxy_hook_installed", True)

    def _protect_xkernel_proxy_controls(self, kernel_proxy_module: Any) -> None:
        protected = getattr(kernel_proxy_module, "PROTECTED_KERNEL_NAMES", frozenset())
        xkernel_controls = {
            "patch_manager",
            "xpatch",
            "patches",
            "apply_patches",
            "apply_patches_for_module",
            "enable_stealth_mode",
            "disable_stealth_mode",
            "set_xpatch_events_enabled",
            "set_xpatch_hot_reload_enabled",
            "set_extera_proxy_all",
            "set_extera_proxy_modules",
            "set_extera_proxy_scopes",
            "add_extera_proxy_module",
            "remove_extera_proxy_module",
            "clear_extera_proxy_modules",
            "extera_proxy_status",
        }
        try:
            kernel_proxy_module.PROTECTED_KERNEL_NAMES = frozenset(
                set(protected) | xkernel_controls
            )
        except Exception:
            pass

    def _patch_extera_proxy_function(
        self,
        module: Any,
        attr_name: str,
        original_attr_name: str,
        factory: Any,
    ) -> None:
        current = getattr(module, attr_name, None)
        if current is None:
            return
        original = object.__getattribute__(self, original_attr_name)
        if original is None:
            original = getattr(current, "__xpatch_extera_original__", current)
            object.__setattr__(self, original_attr_name, original)
        if getattr(current, "__xpatch_extera_kernel_id__", None) == id(self):
            return
        wrapper = factory(original)
        wrapper.__xpatch_extera_original__ = original
        wrapper.__xpatch_extera_kernel_id__ = id(self)
        setattr(module, attr_name, wrapper)

    def _patch_extera_client_proxy_class(self, kernel_proxy_module: Any) -> None:
        current = getattr(kernel_proxy_module, "ClientProxy", None)
        if current is None:
            return
        original = object.__getattribute__(self, "_xpatch_extera_original_client_proxy_class")
        if original is None:
            original = getattr(current, "__xpatch_extera_original__", current)
            object.__setattr__(self, "_xpatch_extera_original_client_proxy_class", original)
        if getattr(current, "__xpatch_extera_kernel_id__", None) == id(self):
            return
        wrapper = self._make_extera_client_proxy(original)
        wrapper.__xpatch_extera_original__ = original
        wrapper.__xpatch_extera_kernel_id__ = id(self)
        setattr(kernel_proxy_module, "ClientProxy", wrapper)

    def _patch_extera_proxy_imported_wrappers(self, kernel_proxy_module: Any) -> None:
        # Several core modules import proxy helpers directly. Patch module-level
        # aliases too, otherwise old aliases keep returning EventProxy/ClientProxy.
        import sys

        replacements = {
            "get_module_kernel": getattr(kernel_proxy_module, "get_module_kernel", None),
            "get_module_client": getattr(kernel_proxy_module, "get_module_client", None),
            "wrap_event_for_module": getattr(kernel_proxy_module, "wrap_event_for_module", None),
            "ClientProxy": getattr(kernel_proxy_module, "ClientProxy", None),
        }
        originals = {
            name: getattr(wrapper, "__xpatch_extera_original__", None)
            for name, wrapper in replacements.items()
            if wrapper is not None
        }

        for module_name, module in list(sys.modules.items()):
            if not module_name.startswith("core."):
                continue
            for attr_name, wrapper in replacements.items():
                if wrapper is None or not hasattr(module, attr_name):
                    continue
                current = getattr(module, attr_name, None)
                original = originals.get(attr_name)
                if (
                    current is original
                    or getattr(current, "__xpatch_extera_original__", None) is original
                    or getattr(current, "__module__", "").startswith("core.")
                ):
                    setattr(module, attr_name, wrapper)

    def _make_extera_get_module_kernel(self, original: Any) -> Any:
        kernel_self = self

        def get_module_kernel_with_extera(kernel: Any, module_name: str, is_system: bool) -> Any:
            if is_system:
                return original(kernel, module_name, is_system)
            should_bypass = object.__getattribute__(kernel_self, "_extera_proxy_should_bypass")
            scope_enabled = object.__getattribute__(kernel_self, "_extera_proxy_scope_enabled")
            if kernel is kernel_self and scope_enabled("kernel") and should_bypass(module_name):
                return kernel
            return original(kernel, module_name, is_system)

        return get_module_kernel_with_extera

    def _apply_extera_proxy_to_loaded_modules(self) -> None:
        raw_client = getattr(self, "client", None)
        if raw_client is None:
            return
        client_scope = self._extera_proxy_scope_enabled("client")
        original_client_proxy = object.__getattribute__(
            self,
            "_xpatch_extera_original_client_proxy_class",
        )
        for module_names, target in self._iter_extera_loaded_module_targets():
            bypass = client_scope and self._extera_proxy_should_bypass_names(module_names)
            display_name = sorted(module_names)[0] if module_names else "<unknown>"
            replacement = raw_client
            if not bypass:
                if original_client_proxy is None:
                    continue
                replacement = original_client_proxy(raw_client, module_name=display_name)
            for attr_name in ("client", "_client"):
                if not hasattr(target, attr_name):
                    continue
                try:
                    current = getattr(target, attr_name)
                    if bypass or current is raw_client:
                        setattr(target, attr_name, replacement)
                except Exception:
                    pass
            allmodules = getattr(target, "allmodules", None)
            if allmodules is not None and hasattr(allmodules, "_client_proxy"):
                try:
                    current = allmodules._client_proxy
                    if bypass or current is raw_client:
                        allmodules._client_proxy = replacement
                except Exception:
                    pass

    def _iter_extera_loaded_module_targets(self) -> list[tuple[set[str], Any]]:
        items: list[tuple[set[str], Any]] = []
        target_aliases: dict[int, set[str]] = {}
        target_objects: dict[int, Any] = {}

        def add(name: Any, target: Any) -> None:
            if target is None:
                return
            target_id = id(target)
            aliases = target_aliases.setdefault(target_id, set())
            aliases.update(self._extera_names_for_target(name, target))
            target_objects[target_id] = target

        for name, module in (getattr(self, "loaded_modules", {}) or {}).items():
            add(name, module)
            add(name, getattr(module, "_class_instance", None))
        for name, instance in (getattr(self, "_class_module_instances", {}) or {}).items():
            add(name, instance)
        for target_id, aliases in target_aliases.items():
            items.append(({item for item in aliases if item}, target_objects[target_id]))
        return items

    def _extera_names_for_target(self, name: Any, target: Any) -> set[str]:
        names = {
            self._normalize_extera_module_name(name),
            self._normalize_extera_module_name(getattr(target, "name", "")),
            self._normalize_extera_module_name(getattr(target, "__name__", "")),
            self._normalize_extera_module_name(type(target).__name__),
        }
        return {item for item in names if item}

    def _make_extera_client_proxy(self, original: Any) -> Any:
        kernel_self = self

        def ClientProxy_with_extera(client: Any, module_name: str) -> Any:
            should_bypass = object.__getattribute__(kernel_self, "_extera_proxy_should_bypass")
            scope_enabled = object.__getattribute__(kernel_self, "_extera_proxy_scope_enabled")
            kernel_client = getattr(kernel_self, "client", None)
            if client is kernel_client and scope_enabled("client") and should_bypass(module_name):
                return client
            return original(client, module_name)

        return ClientProxy_with_extera

    def _make_extera_get_module_client(self, original: Any) -> Any:
        kernel_self = self

        def get_module_client_with_extera(kernel: Any, module_name: str, is_system: bool) -> Any:
            if is_system:
                return original(kernel, module_name, is_system)
            should_bypass = object.__getattribute__(kernel_self, "_extera_proxy_should_bypass")
            scope_enabled = object.__getattribute__(kernel_self, "_extera_proxy_scope_enabled")
            if kernel is kernel_self and scope_enabled("client") and should_bypass(module_name):
                return kernel.client
            return original(kernel, module_name, is_system)

        return get_module_client_with_extera

    def _make_extera_wrap_event_for_module(self, original: Any) -> Any:
        kernel_self = self

        def wrap_event_for_module_with_extera(event: Any, module_name: str, kernel: Any) -> Any:
            should_bypass = object.__getattribute__(kernel_self, "_extera_proxy_should_bypass")
            scope_enabled = object.__getattribute__(kernel_self, "_extera_proxy_scope_enabled")
            if kernel is kernel_self and scope_enabled("event") and should_bypass(module_name):
                return event
            return original(event, module_name, kernel)

        return wrap_event_for_module_with_extera

    def _extera_proxy_should_bypass_names(self, module_names: set[str]) -> bool:
        modules = object.__getattribute__(self, "_xpatch_extera_proxy_modules")
        if bool(object.__getattribute__(self, "_xpatch_extera_proxy_all")):
            return module_names.isdisjoint(modules)
        return bool(module_names & modules)

    def _extera_proxy_should_bypass(self, module_name: Any) -> bool:
        modules = object.__getattribute__(self, "_xpatch_extera_proxy_modules")
        normalized = self._normalize_extera_module_name(module_name)
        if bool(object.__getattribute__(self, "_xpatch_extera_proxy_all")):
            return normalized not in modules
        return normalized in modules

    def _extera_proxy_scope_enabled(self, scope: str) -> bool:
        scopes = object.__getattribute__(self, "_xpatch_extera_proxy_scopes")
        return "root" in scopes or str(scope).casefold() in scopes

    @staticmethod
    def _coerce_extera_modules(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = value.replace("\n", ",").split(",")
        elif isinstance(value, (list, tuple, set, frozenset)):
            raw_items = list(value)
        else:
            raw_items = [value]
        return [str(item).strip() for item in raw_items if str(item).strip()]

    @staticmethod
    def _normalize_extera_module_name(value: Any) -> str:
        return str(value).strip().casefold() if value is not None else ""

    async def run(self) -> None:
        print('Start RUN')
        self._install_extera_proxy_hook()
        if not getattr(self, "_xpatch_stealth_mode", False):
            self.CORE_NAME = "XPatchKernel"
        if not self.xpatch_safe_mode_enabled():
            await self._xpatch_manager().apply_for_target(_MAGIC_PRE_LOAD_TARGET, force=True)
            await self._xpatch_manager().apply_for_target(_MAGIC_KERNEL_TARGET, force=True)
        await super().run()

    def set_xpatch_events_enabled(self, enabled: bool) -> None:
        object.__setattr__(self, "_xpatch_events_enabled", bool(enabled))

    def set_xpatch_hot_reload_enabled(
        self,
        enabled: bool,
        *,
        interval: float | None = None,
    ) -> None:
        object.__setattr__(self, "_xpatch_hot_reload_enabled", bool(enabled))
        if interval is not None:
            object.__setattr__(self, "_xpatch_hot_reload_interval", max(float(interval), 0.5))
        if enabled:
            self._start_xpatch_hot_reload()
        else:
            self._stop_xpatch_hot_reload()

    def _start_xpatch_hot_reload(self) -> None:
        task = object.__getattribute__(self, "_xpatch_hot_reload_task")
        if task is not None and not task.done():
            return
        object.__setattr__(
            self,
            "_xpatch_hot_reload_task",
            asyncio.create_task(self._watch_xpatch_files()),
        )

    def _stop_xpatch_hot_reload(self) -> None:
        task = object.__getattribute__(self, "_xpatch_hot_reload_task")
        if task is not None and not task.done():
            task.cancel()
        object.__setattr__(self, "_xpatch_hot_reload_task", None)

    async def _watch_xpatch_files(self) -> None:
        while bool(object.__getattribute__(self, "_xpatch_hot_reload_enabled")):
            interval = float(object.__getattribute__(self, "_xpatch_hot_reload_interval"))
            await asyncio.sleep(interval)
            try:
                await self._xpatch_manager().reload_changed_patches()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger = getattr(self, "logger", None)
                log_method = getattr(logger, "debug", None)
                if callable(log_method):
                    log_method("[xpatch] hot reload check failed: %s", e)

    def _install_xpatch_loader_hooks(self) -> None:
        loader = getattr(self, "_loader", None)
        if loader is None or getattr(loader, "_xpatch_hooks_installed", False):
            return

        load_module_from_file = getattr(loader, "load_module_from_file", None)
        if callable(load_module_from_file):

            async def load_module_from_file_with_patches(*args: Any, **kwargs: Any) -> Any:
                result = await load_module_from_file(*args, **kwargs)
                if self._xpatch_load_result_ok(result):
                    target_hint = self._xpatch_target_hint(args, kwargs)
                    if target_hint:
                        await self._xpatch_manager().apply_for_target(target_hint, force=True)
                    await self._xpatch_manager().apply_all()
                return result

            loader.load_module_from_file = load_module_from_file_with_patches

        load_system_modules = getattr(loader, "load_system_modules", None)
        if callable(load_system_modules):

            async def load_system_modules_with_patches(*args: Any, **kwargs: Any) -> Any:
                result = await load_system_modules(*args, **kwargs)
                await self._xpatch_manager().apply_all()
                return result

            loader.load_system_modules = load_system_modules_with_patches

        load_user_modules = getattr(loader, "load_user_modules", None)
        if callable(load_user_modules):

            async def load_user_modules_with_patches(*args: Any, **kwargs: Any) -> Any:
                result = await load_user_modules(*args, **kwargs)
                self._xpatch_full_load_complete = True
                await self._xpatch_manager().apply_for_target(
                    _MAGIC_FULL_LOAD_TARGET,
                    force=True,
                )
                await self._xpatch_manager().apply_all()
                self._schedule_xpatch_retry_after_full_load()
                return result

            loader.load_user_modules = load_user_modules_with_patches

        loader._xpatch_hooks_installed = True

    def _schedule_xpatch_retry_after_full_load(self) -> None:
        task = object.__getattribute__(self, "_xpatch_retry_task")
        if task is not None and not task.done():
            return
        object.__setattr__(
            self,
            "_xpatch_retry_task",
            asyncio.create_task(self._retry_xpatch_after_full_load()),
        )

    async def _retry_xpatch_after_full_load(self) -> None:
        # Some modules finish their own async readiness right after the loader
        # returns. Retry a few times so pending/early-failed patches (for
        # example UI/string patches) do not require manual Apply all.
        for delay in (0.05, 0.25, 1.0, 3.0):
            await asyncio.sleep(delay)
            pm = self._xpatch_manager()
            if not pm.pending_patches and not pm.failed_patches:
                return
            try:
                await pm.apply_all()
            except Exception as e:
                logger = getattr(self, "logger", None)
                log_method = getattr(logger, "debug", None)
                if callable(log_method):
                    log_method("[xpatch] delayed retry failed: %s", e)

    @staticmethod
    def _xpatch_load_result_ok(result: Any) -> bool:
        if isinstance(result, tuple) and result:
            return bool(result[0])
        if result is None:
            return True
        return bool(result)

    @staticmethod
    def _xpatch_target_hint(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
        module_name = kwargs.get("module_name")
        if module_name is None and len(args) > 1:
            module_name = args[1]
        if module_name:
            return str(module_name)

        file_path = kwargs.get("file_path")
        if file_path is None and args:
            file_path = args[0]
        if file_path:
            return Path(str(file_path)).stem
        return None


# Patch
Kernel = XPatchKernel
