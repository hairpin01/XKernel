from __future__ import annotations

import hashlib
import importlib.util
import inspect
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from .standard import Kernel as KernelBase

_PATCH_TARGET_ATTRS = ("PATCH_TARGET", "patch_target", "target")
_PATCH_TARGETS_ATTRS = ("PATCH_TARGETS", "patch_targets", "targets")
_PATCH_APPLY_ATTRS = ("apply_patch", "patch", "apply")


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
        self.failed_patches: dict[tuple[str, str], str] = {}

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
        }

        for patch_key, patch_module in self.load_patches().items():
            patch_name = self._patch_display_name(patch_module, patch_key)
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

        target = self.lookup_target(target_name)
        patch_name = self._patch_display_name(patch_module, patch_key)
        if target is None:
            self._remember_pending(patch_key, target_name)
            self._log(
                "debug",
                "[xpatch] patch %s is pending: target %s is not loaded",
                patch_name,
                target_name,
            )
            return "pending"

        apply_callback = self._apply_callback(patch_module)
        if apply_callback is None:
            self.failed_patches[applied_key] = "Patch apply callback is not declared"
            self._log(
                "warning",
                "[xpatch] patch %s has no apply_patch/patch/apply callback",
                patch_name,
            )
            return "failed"

        try:
            patch_result = self._call_patch_callback(apply_callback, target)
            if inspect.isawaitable(patch_result):
                patch_result = await patch_result
        except Exception as e:
            self.failed_patches[applied_key] = str(e)
            self._log(
                "error",
                "[xpatch] patch %s failed for %s: %s",
                patch_name,
                target_name,
                e,
            )
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
        return "applied"

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
                self._log("error", "[xpatch] failed to load %s: %s", file_path, e)

        for stale_key in set(self.loaded_patches) - seen:
            self.loaded_patches.pop(stale_key, None)
            self._patch_states.pop(stale_key, None)
            self.pending_patches.pop(stale_key, None)

        return dict(self.loaded_patches)

    def lookup_target(self, module_name: str) -> Any | None:
        """Find a loaded MCUB module or class-style module instance by name."""

        needle = self._normalize(module_name)

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
        self.pending_patches.pop(patch_key, None)

    def _forget_applied_targets(self, target_aliases: set[str]) -> None:
        for applied_key in list(self.applied_patches):
            if applied_key[1] in target_aliases:
                self.applied_patches.pop(applied_key, None)

    def _remember_pending(self, patch_key: str, target_name: str) -> None:
        pending = self.pending_patches.setdefault(patch_key, [])
        if target_name not in pending:
            pending.append(target_name)

    def _drop_pending(self, patch_key: str, target_name: str) -> None:
        pending = self.pending_patches.get(patch_key)
        if not pending:
            return
        target_norm = self._normalize(target_name)
        self.pending_patches[patch_key] = [
            item for item in pending if self._normalize(item) != target_norm
        ]
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

    def __init__(self) -> None:
        super().__init__()

        self.ver = f"{self.VERSION}:XPatch"
        self.VERSION = self.ver

        self.patch_manager = XPatchPatchManager(self)
        self.xpatch = self.patch_manager
        self.patches = self.patch_manager
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

        return await self.patch_manager.apply_all(target_name=target_name, force=force)

    async def apply_patches_for_module(
        self,
        module_name: str,
        *,
        force: bool = True,
    ) -> dict[str, list[tuple[str, str]]]:
        """Re-apply XPatch patches for one loaded module."""

        return await self.patch_manager.apply_for_target(module_name, force=force)

    async def run(self) -> None:
        print('Start RUN')
        self.CORE_NAME = "XPatchKernel"
        await super().run()

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
                        await self.patch_manager.apply_for_target(target_hint, force=True)
                    await self.patch_manager.apply_all()
                return result

            loader.load_module_from_file = load_module_from_file_with_patches

        load_system_modules = getattr(loader, "load_system_modules", None)
        if callable(load_system_modules):

            async def load_system_modules_with_patches(*args: Any, **kwargs: Any) -> Any:
                result = await load_system_modules(*args, **kwargs)
                await self.patch_manager.apply_all()
                return result

            loader.load_system_modules = load_system_modules_with_patches

        load_user_modules = getattr(loader, "load_user_modules", None)
        if callable(load_user_modules):

            async def load_user_modules_with_patches(*args: Any, **kwargs: Any) -> Any:
                result = await load_user_modules(*args, **kwargs)
                await self.patch_manager.apply_all()
                return result

            loader.load_user_modules = load_user_modules_with_patches

        loader._xpatch_hooks_installed = True

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
