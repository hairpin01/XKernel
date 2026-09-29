from __future__ import annotations

import ast
import asyncio
import contextlib
import hashlib
import html
import inspect
import io
import os
import re
import secrets
import shutil
import tempfile
import time
import tokenize
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp

import utils
from core.lib.loader.module_base import ModuleBase, callback, command
from core.lib.loader.module_config import (
    Boolean,
    ConfigValue,
    DictType,
    Integer,
    ModuleConfig,
    Placeholders,
    String,
)
from utils.platform import get_platform_name

from cubkit import load_strings


class XKernelInstaller(ModuleBase):
    name = "XPatchKernelManager"
    version = "1.5.2"
    author = "@Hairpin00"
    description = {
        "ru": "Менеджер и установщик XKernel core/патчей для MCUB",
        "en": "XKernel core/patch manager & installer for MCUB",
    }
    dependencies = ["aiohttp"]

    strings = load_strings()

    config = ModuleConfig(
        ConfigValue(
            "stealth_mode",
            False,
            description="Hide XPatch markers and protect XKernel attrs with CallInsecure",
            validator=Boolean(default=False),
        ),
        ConfigValue(
            "auto_update_kernel",
            False,
            description="Automatically install a newer XKernel when VERSION_XKERNEL increases",
            validator=Boolean(default=False),
        ),
        ConfigValue(
            "update_notifications",
            True,
            description="Send XKernel update notifications from bot to log chat or client DM",
            validator=Boolean(default=True),
        ),
        ConfigValue(
            "manager_update_notifications",
            True,
            description="Send notifications when XPatchKernelManager has a newer repository version",
            validator=Boolean(default=True),
        ),
        ConfigValue(
            "update_notification_delay",
            0,
            description="Delay before sending update notifications in seconds: 0, 30, 60, or 300",
            validator=Integer(default=0, min=0, max=300),
        ),
        ConfigValue(
            "experimental_patch_events",
            False,
            description="Experimental: emit xpatch:* events after patch lifecycle actions",
            validator=Boolean(default=False),
        ),
        ConfigValue(
            "experimental_patch_hot_reload",
            False,
            description="Experimental: watch patch files and hot-reload changed patches",
            validator=Boolean(default=False),
        ),
        ConfigValue(
            "experimental_hot_reload_smart_disable",
            False,
            description="Temporarily quarantine patches that fail during hot reload",
            validator=Boolean(default=False),
        ),
        ConfigValue(
            "experimental_hot_reload_retry_interval",
            30,
            description="Seconds before hot reload retries a quarantined patch",
            validator=Integer(default=30, min=1, max=3600),
        ),
        ConfigValue(
            "experimental_hot_reload_disable_on_first_fail",
            False,
            description="Disable patch after first failed hot reload load attempt",
            validator=Boolean(default=False),
        ),
        ConfigValue(
            "experimental_hot_load_new_patches",
            False,
            description="Load newly added patch files while hot reload is running",
            validator=Boolean(default=False),
        ),
        ConfigValue(
            "extera_proxy_all",
            False,
            description="Dangerous: disable ModuleKernelProxy for all user modules",
            validator=Boolean(default=False),
        ),
        ConfigValue(
            "extera_proxy_modules",
            "",
            description="Comma-separated modules with ModuleKernelProxy disabled",
            validator=String(default=""),
        ),
        ConfigValue(
            "extera_proxy_scopes",
            "kernel",
            description="Comma-separated ExteraProxy scopes: kernel, client, event",
            validator=String(default="kernel"),
        ),
        ConfigValue(
            "mcmac_enabled",
            False,
            description="Enable XKernel MCMAC runtime layer",
            validator=Boolean(default=False),
        ),
        ConfigValue(
            "mcmac_mode",
            "permissive",
            description="MCMAC mode: permissive or enforcing",
            validator=String(default="permissive"),
        ),
        ConfigValue(
            "mcmac_audit_mode",
            "all",
            description="MCMAC audit/logging mode: all, denied, blocked, off",
            validator=String(default="all"),
        ),
        ConfigValue(
            "mcmac_module_types",
            {},
            description="JSON map of persistent MCMAC module type overrides",
            validator=DictType(default={}, key_type=str, value_type=str),
        ),
        ConfigValue(
            "system_patch_man_extera",
            False,
            description="Add ExteraProxy info to man module details",
            validator=Boolean(default=False),
        ),
        ConfigValue(
            "system_patch_man_mcmac",
            False,
            description="Add MCMAC info to man module details",
            validator=Boolean(default=False),
        ),
        ConfigValue(
            "system_patch_updates_xkernel",
            False,
            description="Add XKernel status to updates.update command",
            validator=Boolean(default=False),
        ),
        ConfigValue(
            "client_patch_app_version",
            "",
            description="Client Patch app_version override",
            validator=String(default=""),
        ),
        ConfigValue(
            "client_patch_device_model",
            "",
            description="Client Patch device_model override",
            validator=String(default=""),
        ),
        ConfigValue(
            "client_patch_system_version",
            "",
            description="Client Patch system_version override",
            validator=String(default=""),
        ),
        ConfigValue(
            "client_patch_lang_code",
            "",
            description="Client Patch lang_code override",
            validator=String(default=""),
        ),
        ConfigValue(
            "client_patch_system_lang_code",
            "",
            description="Client Patch system_lang_code override",
            validator=String(default=""),
        ),
        ConfigValue(
            "live_logs_max_lines",
            "10",
            description="Live [xpatch] logs line limit: 5, 10, 20, or 25",
            validator=String(default="10"),
        ),
        ConfigValue(
            "live_logs_refresh_interval",
            "5",
            description="Live [xpatch] logs refresh interval in seconds: 5, 10, or 15",
            validator=String(default="5"),
        ),
        ConfigValue(
            "xkernel_custom_text_no_core",
            "XPatchKernel не активен",
            description="Custom text for {xkernel_custom_text} when another core is active",
            validator=Placeholders(
                default="XPatchKernel не активен",
                placeholder_scope="any",
            ),
        ),
        ConfigValue(
            "xkernel_custom_text_installed",
            "XKernel установлен",
            description="Custom text for {xkernel_custom_text} when XKernel is installed and active",
            validator=Placeholders(
                default="XKernel установлен",
                placeholder_scope="any",
            ),
        ),
        ConfigValue(
            "xkernel_custom_text_stealth",
            "Stealth mode включён",
            description="Custom text for {xkernel_custom_text} when stealth mode is enabled",
            validator=Placeholders(
                default="Stealth mode включён",
                placeholder_scope="any",
            ),
        ),
        ConfigValue(
            "xkernel_custom_text_not_installed",
            "XKernel не установлен",
            description="Custom text for {xkernel_custom_text} when core/kernel/XKernel.py is missing",
            validator=Placeholders(
                default="XKernel не установлен",
                placeholder_scope="any",
            ),
        ),
        ConfigValue(
            "placeholders",
            "",
            description="Available XKernel placeholders",
            validator=String(default=""),
        ),
    )

    X_RAW_ROOT = "https://raw.githubusercontent.com/hairpin01/XKernel/refs/heads/main"
    X_KERNEL_URL = f"{X_RAW_ROOT}/XKernel.py"
    X_MANAGER_URL = f"{X_RAW_ROOT}/XPatchKernelManager.py"
    X_KERNEL_REPO = "https://github.com/hairpin01/XKernel"
    X_HASH_FILE_NAME = "SHA256:hash.txt"
    SHA256_RE = re.compile(r"\b[a-fA-F0-9]{64}\b")
    MANAGER_UPDATE_CACHE_TTL = 6 * 60 * 60

    async def on_load(self) -> None:
        await super().on_load()
        self.CUSTOM_EMOJI = {
            "loading": '<tg-emoji emoji-id="5260348422266822411">💬</tg-emoji>',
            "install": '<tg-emoji emoji-id="5327790373865530387">🫥</tg-emoji>',
            "true": '<tg-emoji emoji-id="5776375003280838798">✅</tg-emoji>',
            "lock": '<tg-emoji emoji-id="5832546462478635761">🔒</tg-emoji>',
            "moon": '<tg-emoji emoji-id="5258011861273551368">🌘</tg-emoji>',
            "settings": '<tg-emoji emoji-id="5258096772776991776">⚙</tg-emoji>',
            "file": '<tg-emoji emoji-id="5257965810634202885">📁</tg-emoji>',
            "menu": '<tg-emoji emoji-id="5226513232549664618">🔢</tg-emoji>',
            "info": '<tg-emoji emoji-id="5879785854284599288">ℹ️</tg-emoji>',
            "warning": '<tg-emoji emoji-id="5253959125838090076">👁</tg-emoji>',
            "reboot": '<tg-emoji emoji-id="5260348422266822411">🥽</tg-emoji>',
            "back": '<tg-emoji emoji-id="5877629862306385808">🔙</tg-emoji>',
            "+": '<tg-emoji emoji-id="5274008024585871702">➕</tg-emoji>',
            "dir": '<tg-emoji emoji-id="5257969839313526622">📂</tg-emoji>',
            "pc": '<tg-emoji emoji-id="5258260149037965799">💼</tg-emoji>',
            "diskette": '<tg-emoji emoji-id="5877316724830768997">🗃</tg-emoji>',
            "reload": '<tg-emoji emoji-id="6005843436479975944">🔁</tg-emoji>',
            "injection": '<tg-emoji emoji-id="5120959729736090635">🧬</tg-emoji>',
            "command": '<tg-emoji emoji-id="5875450995332353523">🔨</tg-emoji>',
            "бууу": '<tg-emoji emoji-id="5897962422169243693">👻</tg-emoji>',
            "on": '<tg-emoji emoji-id="5985596818912712352">✅</tg-emoji>',
            "off": '<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji>',
            "v1": '<tg-emoji emoji-id="5794182096603847292">1⃣</tg-emoji>',
            "v5": '<tg-emoji emoji-id="5794066823976592976">5️⃣</tg-emoji>',
            "v10": '<tg-emoji emoji-id="5794310013614824017">1⃣</tg-emoji>',
            "magic": '<tg-emoji emoji-id="5785326857587003471">🪄</tg-emoji>',
            "utils": '<tg-emoji emoji-id="5884290437459480896">📸</tg-emoji>',
            "logs": '<tg-emoji emoji-id="5960551395730919906">📝</tg-emoji>',
            "pending": '<tg-emoji emoji-id="5839380464116175529">✏️</tg-emoji>',
            "result": '<tg-emoji emoji-id="5877540355187937244">📤</tg-emoji>',
            "phone": '<tg-emoji emoji-id="5407025283456835913">📱</tg-emoji>',
            "catalog": '<tg-emoji emoji-id="5258423306255604960">💻</tg-emoji>',
            "repo": '<tg-emoji emoji-id="5257963315258204021">🏘</tg-emoji>',
            "add": '<tg-emoji emoji-id="5257991477358763590">↗️</tg-emoji>',
            "delete": '<tg-emoji emoji-id="5778527486270770928">❌</tg-emoji>',
            "rebuild": '<tg-emoji emoji-id="5891093751555694829">🎭</tg-emoji>',
        }
        self.C = self.CUSTOM_EMOJI
        await self._load_config()
        utils.register_decorated_placeholders(self.name, self)
        self.config["placeholders"] = utils.format_placeholders(self.name)
        await self._save_config()
        await self._load_client_patch_db_status()
        try:
            self._apply_stealth_from_config()
        except RuntimeError as exc:
            self.log.warning("Stealth mode is configured but unavailable: %s", exc)
        self._apply_experimental_from_config()
        self._apply_extera_proxy_from_config()
        self._apply_mcmac_from_config()
        self._apply_system_module_patches_from_config()
        self._apply_client_patch_from_config()
        self._ensure_update_task()
        self.log.info("XKernelInstaller loaded")

    async def on_unload(self) -> None:
        self._stop_live_logs()
        task = getattr(self, "_update_task", None)
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        utils.unregister_scope(self.name)

    def _ensure_update_task(self) -> None:
        if not (
            self._cfg("auto_update_kernel")
            or self._cfg("update_notifications")
            or self._cfg("manager_update_notifications")
            or self._manager_update_cache_stale()
        ):
            return
        task = getattr(self, "_update_task", None)
        if task is None or task.done():
            self._update_task = asyncio.create_task(self._run_update_checks())

    async def _run_update_checks(self) -> None:
        await self._refresh_manager_update_cache()
        if self._cfg("update_notifications") and self._cfg(
            "manager_update_notifications"
        ):
            await self._check_manager_update()
        if self._cfg("auto_update_kernel") or self._cfg("update_notifications"):
            await self._check_kernel_update()

    async def _load_config(self) -> None:
        config_dict = await self.kernel.get_module_config(
            self.name,
            self.config.to_dict(),
        )
        self.config.from_dict(config_dict)
        await self.kernel.save_module_config(self.name, self.config.to_dict())
        self.kernel.store_module_config_schema(self.name, self.config)

    async def _save_config(self) -> None:
        await self.kernel.save_module_config(self.name, self.config.to_dict())
        self.kernel.store_module_config_schema(self.name, self.config)

    def _cfg(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def _kernel_object(self) -> Any:
        try:
            return object.__getattribute__(self.kernel, "_kernel")
        except Exception:
            return self.kernel

    def _kernel_attr(
        self,
        name: str,
        default: Any = None,
        *,
        protected: bool = False,
    ) -> Any:
        kernel = self._kernel_object() if protected else self.kernel
        if protected:
            try:
                return object.__getattribute__(kernel, name)
            except Exception:
                pass
        try:
            return getattr(kernel, name, default)
        except Exception:
            return default

    def _kernel_patch_manager(self) -> Any | None:
        kernel = self._kernel_object()
        try:
            return object.__getattribute__(kernel, "patch_manager")
        except Exception:
            return None

    def _apply_stealth_from_config(self) -> None:
        if not self._cfg("stealth_mode", False):
            return

        try:
            enable_stealth = object.__getattribute__(
                self._kernel_object(),
                "enable_stealth_mode",
            )
        except Exception:
            enable_stealth = None
        if callable(enable_stealth):
            enable_stealth()
            return

        raise RuntimeError(self.strings("stealth_unsupported"))

    def _disable_runtime_stealth(self) -> None:
        try:
            disable_stealth = object.__getattribute__(
                self._kernel_object(),
                "disable_stealth_mode",
            )
        except Exception:
            disable_stealth = None
        if callable(disable_stealth):
            disable_stealth()

    def _set_runtime_patch_events(self, enabled: bool) -> bool:
        try:
            setter = object.__getattribute__(
                self._kernel_object(),
                "set_xpatch_events_enabled",
            )
        except Exception:
            setter = None
        if not callable(setter):
            return False
        setter(enabled)
        return True

    def _set_runtime_hot_reload(self, enabled: bool) -> bool:
        try:
            setter = object.__getattribute__(
                self._kernel_object(),
                "set_xpatch_hot_reload_enabled",
            )
        except Exception:
            setter = None
        if not callable(setter):
            return False
        try:
            setter(
                enabled,
                smart_disable=bool(
                    self._cfg("experimental_hot_reload_smart_disable", False)
                ),
                retry_interval=self._hot_reload_retry_interval(),
                disable_on_first_fail=bool(
                    self._cfg("experimental_hot_reload_disable_on_first_fail", False)
                ),
                hot_load_new_patches=bool(
                    self._cfg("experimental_hot_load_new_patches", False)
                ),
            )
            self._hot_reload_advanced_runtime_supported = True
        except TypeError as exc:
            if "unexpected keyword" not in str(exc):
                raise
            setter(enabled)
            self._hot_reload_advanced_runtime_supported = False
        return True

    def _hot_reload_advanced_supported(self) -> bool:
        try:
            setter = object.__getattribute__(
                self._kernel_object(), "set_xpatch_hot_reload_enabled"
            )
            signature = inspect.signature(setter)
        except Exception:
            return bool(getattr(self, "_hot_reload_advanced_runtime_supported", True))
        params = signature.parameters
        if any(
            param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()
        ):
            return True
        return "smart_disable" in params

    def _hot_reload_retry_interval(self) -> int:
        try:
            value = int(self._cfg("experimental_hot_reload_retry_interval", 30) or 30)
        except (TypeError, ValueError):
            return 30
        return min(max(value, 1), 3600)

    def _apply_experimental_from_config(self) -> None:
        self._set_runtime_patch_events(
            bool(self._cfg("experimental_patch_events", False))
        )
        self._set_runtime_hot_reload(
            bool(self._cfg("experimental_patch_hot_reload", False))
        )

    def _extera_modules_from_config(self) -> list[str]:
        raw = str(self._cfg("extera_proxy_modules", "") or "")
        modules: list[str] = []
        seen: set[str] = set()
        for item in raw.replace("\n", ",").split(","):
            name = item.strip()
            norm = name.casefold()
            if name and norm not in seen:
                seen.add(norm)
                modules.append(name)
        return modules

    def _extera_scopes_from_config(self) -> list[str]:
        allowed = {"kernel", "client", "event", "root"}
        raw = str(self._cfg("extera_proxy_scopes", "kernel") or "kernel")
        scopes: list[str] = []
        for item in raw.replace("\n", ",").split(","):
            scope = item.strip().casefold()
            if scope in allowed and scope not in scopes:
                scopes.append(scope)
        if "root" in scopes or {"kernel", "client", "event"}.issubset(scopes):
            return ["root"]
        return scopes or ["kernel"]

    def _save_extera_scopes_to_config(self, scopes: list[str]) -> None:
        allowed = {"kernel", "client", "event", "root"}
        clean: list[str] = []
        for item in scopes:
            scope = str(item).strip().casefold()
            if scope in allowed and scope not in clean:
                clean.append(scope)
        if "root" in clean or {"kernel", "client", "event"}.issubset(clean):
            clean = ["root"]
        if not clean:
            clean = ["kernel"]
        self.config["extera_proxy_scopes"] = ", ".join(clean)

    def _save_extera_modules_to_config(self, modules: list[str]) -> None:
        seen: set[str] = set()
        clean: list[str] = []
        for item in modules:
            name = str(item).strip()
            norm = name.casefold()
            if name and norm not in seen:
                seen.add(norm)
                clean.append(name)
        self.config["extera_proxy_modules"] = ", ".join(clean)

    def _set_runtime_extera_proxy_all(self, enabled: bool) -> bool:
        try:
            setter = object.__getattribute__(
                self._kernel_object(),
                "set_extera_proxy_all",
            )
        except Exception:
            setter = None
        if not callable(setter):
            return False
        setter(enabled)
        return True

    def _set_runtime_extera_proxy_modules(self, modules: list[str]) -> bool:
        try:
            setter = object.__getattribute__(
                self._kernel_object(),
                "set_extera_proxy_modules",
            )
        except Exception:
            setter = None
        if not callable(setter):
            return False
        setter(modules)
        return True

    def _set_runtime_extera_proxy_scopes(self, scopes: list[str]) -> bool:
        try:
            setter = object.__getattribute__(
                self._kernel_object(),
                "set_extera_proxy_scopes",
            )
        except Exception:
            setter = None
        if not callable(setter):
            return False
        setter(scopes)
        return True

    def _apply_extera_proxy_from_config(self) -> None:
        self._set_runtime_extera_proxy_all(bool(self._cfg("extera_proxy_all", False)))
        self._set_runtime_extera_proxy_modules(self._extera_modules_from_config())
        self._set_runtime_extera_proxy_scopes(self._extera_scopes_from_config())

    def _mcmac_status(self) -> dict[str, Any]:
        try:
            getter = object.__getattribute__(self._kernel_object(), "mcmac_status")
        except Exception as exc:
            return {
                "available": False,
                "enabled": False,
                "mode": "permissive",
                "error": str(exc),
                "path": "",
            }
        if not callable(getter):
            return {
                "available": False,
                "enabled": False,
                "mode": "permissive",
                "error": self.strings("unsupported_current_kernel"),
                "path": "",
            }
        try:
            return dict(getter() or {})
        except Exception as exc:
            return {
                "available": False,
                "enabled": False,
                "mode": "permissive",
                "error": str(exc),
                "path": "",
            }

    def _set_runtime_mcmac_enabled(self, enabled: bool) -> bool:
        try:
            setter = object.__getattribute__(self._kernel_object(), "set_mcmac_enabled")
        except Exception:
            setter = None
        if not callable(setter):
            return False
        return bool(setter(enabled))

    def _set_runtime_mcmac_mode(self, mode: str) -> bool:
        try:
            setter = object.__getattribute__(self._kernel_object(), "set_mcmac_mode")
        except Exception:
            setter = None
        if not callable(setter):
            return False
        return bool(setter(mode))

    def _set_runtime_mcmac_audit_mode(self, audit_mode: str) -> bool:
        try:
            setter = object.__getattribute__(
                self._kernel_object(), "set_mcmac_audit_mode"
            )
        except Exception:
            setter = None
        if not callable(setter):
            return False
        return bool(setter(audit_mode))

    def _set_runtime_mcmac_module_type(
        self, module_name: str, security_type: str
    ) -> bool:
        try:
            setter = object.__getattribute__(
                self._kernel_object(), "set_mcmac_module_type"
            )
        except Exception:
            setter = None
        if not callable(setter):
            return False
        return bool(setter(module_name, security_type))

    def _mcmac_module_types_config(self) -> dict[str, str]:
        data = self._cfg("mcmac_module_types", {}) or {}
        if not isinstance(data, dict):
            return {}
        allowed = {"trusted", "standard", "untrusted", "quarantine"}
        result = {}
        for module_name, security_type in data.items():
            module = str(module_name or "").strip()
            value = str(security_type or "").strip().casefold()
            if module and value in allowed:
                result[module] = value
        return result

    async def _save_mcmac_module_types_config(
        self, module_types: dict[str, str]
    ) -> None:
        self.config["mcmac_module_types"] = dict(sorted(module_types.items()))
        await self._save_config()

    def _clear_runtime_mcmac_module_type(self, module_name: str) -> bool:
        try:
            clearer = object.__getattribute__(
                self._kernel_object(), "clear_mcmac_module_type"
            )
        except Exception:
            clearer = None
        if not callable(clearer):
            return False
        return bool(clearer(module_name))

    async def _refresh_mcmac_runtime(self) -> bool:
        try:
            refresher = object.__getattribute__(
                self._kernel_object(), "refresh_mcmac_runtime"
            )
        except Exception:
            refresher = None
        if not callable(refresher):
            return False
        result = refresher()
        if inspect.isawaitable(result):
            result = await result
        return bool(result)

    def _apply_mcmac_from_config(self) -> None:
        self._set_runtime_mcmac_mode(
            str(self._cfg("mcmac_mode", "permissive") or "permissive")
        )
        self._set_runtime_mcmac_audit_mode(
            str(self._cfg("mcmac_audit_mode", "all") or "all")
        )
        for module_name, security_type in self._mcmac_module_types_config().items():
            self._set_runtime_mcmac_module_type(module_name, security_type)
        self._set_runtime_mcmac_enabled(bool(self._cfg("mcmac_enabled", False)))

    def _set_runtime_system_module_patches(self) -> bool:
        try:
            setter = object.__getattribute__(
                self._kernel_object(), "patch_system_modules"
            )
        except Exception:
            setter = None
        if not callable(setter):
            return False
        return bool(
            setter(
                man_extera=bool(self._cfg("system_patch_man_extera", False)),
                man_mcmac=bool(self._cfg("system_patch_man_mcmac", False)),
                updates_xkernel=bool(self._cfg("system_patch_updates_xkernel", False)),
            )
        )

    def _system_module_patch_status(self) -> dict[str, Any]:
        try:
            getter = object.__getattribute__(
                self._kernel_object(), "system_module_patch_status"
            )
        except Exception as exc:
            return {"available": False, "error": str(exc), "options": {}}
        if not callable(getter):
            return {
                "available": False,
                "error": self.strings("system_patch_unsupported"),
                "options": {},
            }
        try:
            status = dict(getter() or {})
            status.setdefault("available", True)
            return status
        except Exception as exc:
            return {"available": False, "error": str(exc), "options": {}}

    def _apply_system_module_patches_from_config(self) -> None:
        self._set_runtime_system_module_patches()

    def _client_patch_options_from_config(self) -> dict[str, str]:
        keys = {
            "app_version": "client_patch_app_version",
            "device_model": "client_patch_device_model",
            "system_version": "client_patch_system_version",
            "lang_code": "client_patch_lang_code",
            "system_lang_code": "client_patch_system_lang_code",
        }
        options: dict[str, str] = {}
        for option_name, config_key in keys.items():
            value = str(self._cfg(config_key, "") or "").strip()
            if value:
                options[option_name] = value
        return options

    def _client_patch_supported(self) -> bool:
        try:
            patcher = object.__getattribute__(
                self._kernel_object(),
                "patch_core_lib_client",
            )
        except Exception:
            patcher = None
        return callable(patcher)

    def _set_runtime_client_patch(self, enabled: bool) -> bool:
        kernel = self._kernel_object()
        try:
            patcher = object.__getattribute__(kernel, "patch_core_lib_client")
        except Exception:
            patcher = None
        if not callable(patcher):
            return False
        patcher(enabled=enabled, **self._client_patch_options_from_config())
        return True

    def _clear_runtime_client_patch(self) -> bool:
        kernel = self._kernel_object()
        try:
            clearer = object.__getattribute__(kernel, "clear_core_lib_client_patch")
        except Exception:
            clearer = None
        if callable(clearer):
            clearer()
            return True
        return self._set_runtime_client_patch(False)

    def _is_client_patch_enabled(self) -> bool:
        return bool(getattr(self, "_client_patch_enabled_db", False))

    def _apply_client_patch_from_config(self) -> None:
        if self._is_client_patch_enabled():
            self._set_runtime_client_patch(True)
        else:
            self._clear_runtime_client_patch()

    async def _load_client_patch_db_status(self) -> None:
        enabled = False
        db_get = getattr(self.kernel, "db_get", None)
        if callable(db_get):
            try:
                result = db_get(self.name, "client_patch")
                value = await result if inspect.isawaitable(result) else result
                if isinstance(value, bool):
                    enabled = value
                else:
                    enabled = str(value or "").strip().casefold() in {
                        "client patch: on",
                        "on",
                        "true",
                        "1",
                        "yes",
                    }
            except Exception as exc:
                self.log.debug("cannot load Client Patch status from db: %s", exc)
        self._client_patch_enabled_db = enabled
        await self._save_client_patch_db_state()

    async def _save_client_patch_db_status(self) -> None:
        db_set = getattr(self.kernel, "db_set", None)
        if not callable(db_set):
            return
        status = (
            "Client Patch: ON"
            if self._is_client_patch_enabled()
            else "Client Patch: OFF"
        )
        try:
            result = db_set(self.name, "client_patch", status)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            self.log.debug("cannot save Client Patch status to db: %s", exc)

    async def _save_client_patch_db_options(self) -> None:
        db_set = getattr(self.kernel, "db_set", None)
        if not callable(db_set):
            return
        mapping = {
            "client_patch_app_version": "client_patch_app_version",
            "client_patch_device_model": "client_patch_device_model",
            "client_patch_system_version": "client_patch_system_version",
            "client_patch_lang_code": "client_patch_lang_code",
            "client_patch_system_lang_code": "client_patch_system_lang_code",
        }
        try:
            for db_key, config_key in mapping.items():
                value = str(self._cfg(config_key, "") or "").strip()
                result = db_set(self.name, db_key, value)
                if inspect.isawaitable(result):
                    await result
        except Exception as exc:
            self.log.debug("cannot save Client Patch options to db: %s", exc)

    async def _save_client_patch_db_state(self) -> None:
        await self._save_client_patch_db_status()
        await self._save_client_patch_db_options()

    def _client_patch_status_label(self) -> str:
        if not self._client_patch_supported():
            return self.strings("status_not_supported")
        if not self._is_client_patch_enabled():
            return self.strings("status_disabled")
        count = len(self._client_patch_options_from_config())
        if not count:
            return self.strings("status_enabled_no_params")
        return self.strings("status_enabled_params", count=count)

    def _extera_proxy_status_label(self) -> str:
        if self._get_pm() is None:
            return self.strings("status_not_supported")
        count = len(self._extera_modules_from_config())
        if bool(self._cfg("extera_proxy_all", False)):
            if count:
                return self.strings("extera_forced_all_except", count=count)
            return self.strings("extera_forced_all")
        if count == 0:
            return self.strings("extera_inactive")
        return self.strings("extera_forced_selected", count=count)

    def _clear_text(self, text) -> str:
        return re.sub(r"<[^>]+>", "", text)

    def _live_logs_max_lines(self) -> int:
        return self._choice_int("live_logs_max_lines", {5, 10, 20, 25}, 10)

    def _live_logs_refresh_interval(self) -> int:
        return self._choice_int("live_logs_refresh_interval", {5, 10, 15}, 5)

    def _choice_int(self, key: str, allowed: set[int], default: int) -> int:
        try:
            value = int(str(self._cfg(key, default)).strip())
        except (TypeError, ValueError):
            return default
        return value if value in allowed else default

    def _kernel_log_path(self) -> Path:
        return self._repo_root() / "logs" / "kernel.log"

    async def _xpatch_log_lines(self, limit: int | None = None) -> list[str]:
        path = self._kernel_log_path()
        if limit is None:
            limit = self._live_logs_max_lines()

        def read_lines() -> list[str]:
            if not path.exists():
                return []
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                return []
            return [line for line in lines if "[xpatch]" in line][-limit:]

        return await asyncio.to_thread(read_lines)

    async def _build_live_logs_page(self) -> tuple[str, list]:
        C = self.C
        max_lines = self._live_logs_max_lines()
        interval = self._live_logs_refresh_interval()
        lines = await self._xpatch_log_lines(max_lines)
        if lines:
            body = "\n".join(html.escape(line[-220:]) for line in lines)
        else:
            body = self.strings("logs_empty")
        text = (
            f"{C['logs']} <b>{self.strings('logs_title')}</b>\n"
            f"<blockquote>{self.strings('logs_desc', max_lines=max_lines, interval=interval)}</blockquote>\n"
            f"<code>{html.escape(str(self._kernel_log_path()))}</code>\n\n"
            f"<pre>{body}</pre>"
        )
        next_lines = self._next_live_logs_max_lines(max_lines)
        next_interval = self._next_live_logs_refresh_interval(interval)
        buttons = [
            [
                self.Button.inline(
                    self.strings(
                        "logs_lines_button", current=max_lines, next=next_lines
                    ),
                    self.on_cycle_live_logs_lines,
                    ttl=600,
                ),
                self.Button.inline(
                    self.strings(
                        "logs_interval_button", current=interval, next=next_interval
                    ),
                    self.on_cycle_live_logs_interval,
                    ttl=600,
                ),
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                    self.on_back_to_utils,
                    ttl=600,
                )
            ],
        ]
        return text, buttons

    async def _refresh_live_logs(self) -> bool:
        call = getattr(self, "_live_logs_event", None)
        if call is None:
            return False
        try:
            text, buttons = await self._build_live_logs_page()
            await call.edit(text, buttons=buttons)
            return True
        except Exception as exc:
            self.log.debug("cannot refresh XKernel live logs: %s", exc)
            return False

    def _ensure_live_logs_task(self) -> None:
        task = getattr(self, "_live_logs_task", None)
        if task is None or task.done():
            self._live_logs_task = asyncio.create_task(self._live_logs_loop())

    def _stop_live_logs(self) -> None:
        self._live_logs_event = None
        task = getattr(self, "_live_logs_task", None)
        if task and not task.done():
            task.cancel()
        self._live_logs_task = None

    async def _live_logs_loop(self) -> None:
        try:
            while getattr(self, "_live_logs_event", None) is not None:
                await asyncio.sleep(self._live_logs_refresh_interval())
                if not await self._refresh_live_logs():
                    self._stop_live_logs()
                    return
        except asyncio.CancelledError:
            raise

    def _is_xpatch_active(self) -> bool:
        return bool(self._kernel_patch_manager())

    def _get_pm(self):
        """Return patch_manager if XPatchKernel is active, else None."""
        return self._kernel_patch_manager()

    def _patch_stats(self) -> tuple[int, int, int]:
        pm = self._get_pm()
        if pm is None:
            return 0, 0, 0
        applied = len(pm.applied_patches)
        pending = sum(len(v) for v in pm.pending_patches.values())
        failed = len(pm.failed_patches)
        return applied, pending, failed

    def _xkernel_custom_text_template(self) -> str:
        if not self._xkernel_path().exists():
            key = "xkernel_custom_text_not_installed"
        elif self._cfg("stealth_mode", False):
            key = "xkernel_custom_text_stealth"
        elif not self._is_xpatch_active():
            key = "xkernel_custom_text_no_core"
        else:
            key = "xkernel_custom_text_installed"

        return str(self._cfg(key, ""))

    @utils.placeholders("xkernel_version", description="XKernel VERSION_XKERNEL")
    async def _placeholder_xkernel_version(
        self, data: dict[str, Any] | None = None
    ) -> str:
        return self._display_xkernel_version()

    def _extera_proxy_scopes_label(self) -> str:
        if self._get_pm() is None:
            return self.strings("no_access")
        scopes = self._extera_scopes_from_config()
        if "root" in scopes:
            return "Root"
        return ", ".join(scope.title() for scope in scopes)

    @utils.placeholders(
        "extera_proxy_status",
        description="ExteraProxy status: disabled, selected modules, all modules, or all except list",
    )
    async def _placeholder_extera_proxy_status(
        self, data: dict[str, Any] | None = None
    ) -> str:
        return self._extera_proxy_status_label()

    @utils.placeholders(
        "extera_proxy_scopes",
        description="ExteraProxy active scopes: Kernel, Client, Event, or Root",
    )
    async def _placeholder_extera_proxy_scopes(
        self, data: dict[str, Any] | None = None
    ) -> str:
        return self._extera_proxy_scopes_label()

    @utils.placeholders(
        "xkernel_custom_text",
        description="Configured XKernel state text: installed, not installed, stealth, or inactive core",
    )
    async def _placeholder_xkernel_custom_text(
        self, data: dict[str, Any] | None = None
    ) -> str:
        template = self._xkernel_custom_text_template()
        if not template:
            return ""
        return await utils.resolve_placeholders(
            self.name,
            template,
            data={
                "xkernel_version": self._display_xkernel_version(),
                "extera_proxy_status": self._extera_proxy_status_label(),
                "extera_proxy_scopes": self._extera_proxy_scopes_label(),
                "xkernel_custom_text": "",
            },
            strict=False,
        )

    def _build_main_page(self) -> tuple[str, list]:
        C = self.C
        is_xpatch = self._is_xpatch_active()
        ver = html.escape(str(self._kernel_attr("VERSION", "?")))
        core_name = html.escape(str(self._kernel_attr("CORE_NAME", "unknown")))
        xkernel_ver = html.escape(self._display_xkernel_version())
        applied, pending, failed = self._patch_stats()
        stealth = self.strings(
            "state_on" if self._cfg("stealth_mode", False) else "state_off"
        )
        auto_update = self.strings(
            "state_on" if self._cfg("auto_update_kernel", False) else "state_off"
        )
        notifications = self.strings(
            "state_on" if self._cfg("update_notifications", True) else "state_off"
        )
        extera_proxy = html.escape(self._extera_proxy_status_label())

        if is_xpatch:
            text = (
                f"{C['settings']} <b>{self.strings('main_title')}</b>\n\n"
                f"<blockquote>"
                f"{C['true']} <b>XPatchKernel</b> <code>{xkernel_ver}</code>\n"
                f"{C['info']} <em>{self.strings('main_mcub_version')}</em> <code>{ver}</code>\n"
                f"{C['menu']} {self.strings('main_patch_stats', applied=applied, pending=pending, failed=failed)}"
                f"</blockquote>\n"
                f"{C['lock']} {self.strings('main_flags', stealth=stealth, auto_update=auto_update, notifications=notifications)}\n"
                f"{C['injection']} {self.strings('main_extera', status=extera_proxy)}"
            )
        else:
            text = (
                f"{C['settings']} <b>{self.strings('main_title')}</b>\n\n"
                f"{C['lock']} {self.strings('main_core')} <code>{core_name}</code>\n"
                f"{C['info']} {self.strings('main_xkernel_version')} <code>{xkernel_ver}</code>\n\n"
                f"<blockquote>{C['warning']} <i>{self.strings('main_inactive_warning')}</i></blockquote>"
            )

        if self._manager_update_available():
            text += f"\n\n<blockquote>{C['warning']} <b>{self.strings('main_manager_update_warning')}</b></blockquote>"

        buttons: list[list] = []

        if is_xpatch:
            buttons.append(
                [
                    self.Button.inline(
                        f"{self._clear_text(C['menu'])} {self.strings('btn_patches')}",
                        self.on_patches_menu,
                        ttl=600,
                    ),
                    self.Button.inline(
                        f"{self._clear_text(C['info'])} {self.strings('btn_details')}",
                        self.on_details_menu,
                        ttl=600,
                    ),
                ]
            )
            apply_row: list = [
                self.Button.inline(
                    f"{self._clear_text(C['+'])} {self.strings('btn_apply_all')}",
                    self.on_apply_all,
                    ttl=600,
                ),
            ]
            if failed:
                apply_row.append(
                    self.Button.inline(
                        f"{self._clear_text(C['off'])} {self.strings('btn_failed_count', count=failed)}",
                        self.on_patches_menu,
                        ttl=600,
                    )
                )
            buttons.append(apply_row)

        buttons.append(
            [
                self.Button.inline(
                    f"{self._clear_text(C['settings'])} {self.strings('btn_settings')}",
                    self.on_settings_menu,
                    ttl=600,
                ),
                self.Button.inline(
                    f"{self._clear_text(C['reload'])} {self.strings('btn_check_update')}",
                    self.on_check_update,
                    ttl=300,
                ),
                self.Button.inline(
                    f"{self._clear_text(C['utils'])} {self.strings('btn_utils')}",
                    self.on_utils_menu,
                    ttl=600,
                ),
            ]
        )
        buttons.append(
            [
                self.Button.inline(
                    f"{self._clear_text(C['install'])} {self.strings('btn_install_update')}",
                    self.on_install_start,
                    ttl=600,
                ),
            ]
        )
        buttons.append(
            [
                self.Button.url(
                    f"{self._clear_text(self.C['repo'])} {self.strings('btn_repo')}",
                    self.X_KERNEL_REPO,
                ),
            ]
        )

        return text, buttons

    @command(
        "xm",
        alias=["xmanager", "xkm"],
        doc_ru="Открыть менеджер XKernel/патчей",
        doc_en="Open XKernel/patch manager",
    )
    async def cmd_manager(self, event: Any) -> None:
        await self._edit(
            event, f"{self.C['loading']} {self.strings('manager_opening')}"
        )
        text, buttons = self._build_main_page()
        ok, _ = await self.subinline.form(
          event.chat_id, 
          text,
          buttons=buttons, 
          ttl=600,
          reply_to=getattr(event, "reply_to", None),
        )
        if not ok:
            await self._edit(event, f"🚫 {self.strings('manager_open_failed')}")
            return
        try:
            await event.delete()
        except Exception:
            pass

    @callback(ttl=600)
    async def on_back_to_main(self, call) -> None:
        self._stop_live_logs()
        text, buttons = self._build_main_page()
        await call.edit(text, buttons=buttons)

    @staticmethod
    def _canonical_manager_name() -> str:
        return "XPatch" "KernelManager"

    def _manager_rebuild_state(self) -> dict[str, Any]:
        state = getattr(self, "_manager_rebuild_state_data", None)
        if not isinstance(state, dict):
            state = {
                "name": "XPatchKernelManagerFork",
                "delete_current": True,
                "copy_config": True,
                "force_wipe_current_config": False,
            }
            self._manager_rebuild_state_data = state
        return state

    def _validate_manager_rebuild_name(self, name: str) -> str:
        value = str(name or "").strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{2,63}", value):
            raise ValueError(self.strings("rebuild_name_invalid"))
        if value == self._canonical_manager_name():
            raise ValueError(self.strings("rebuild_same_name"))
        return value

    def _random_manager_rebuild_name(self) -> str:
        alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        suffix = "".join(secrets.choice(alphabet) for _ in range(10))
        return f"Manager_{suffix}"

    def _manager_rebuild_source_path(self) -> Path:
        raw = inspect.getsourcefile(type(self)) or globals().get("__file__")
        if not raw:
            raise FileNotFoundError(self.strings("rebuild_source_missing"))
        path = Path(raw)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            raise FileNotFoundError(self.strings("rebuild_source_missing"))
        return path

    def _replace_manager_name_literals(
        self,
        source: str,
        *,
        old_name: str,
        new_name: str,
    ) -> tuple[str, int]:
        tokens: list[tokenize.TokenInfo] = []
        replacements = 0
        stream = io.StringIO(source)
        for token in tokenize.generate_tokens(stream.readline):
            if token.type == tokenize.STRING:
                try:
                    value = ast.literal_eval(token.string)
                except Exception:
                    value = None
                if value == old_name:
                    token = token._replace(string=repr(new_name))
                    replacements += 1
            tokens.append(token)
        return tokenize.untokenize(tokens), replacements

    def _build_rebuilt_manager_source(self, new_name: str) -> tuple[str, int]:
        current_name = str(getattr(self, "name", ""))
        if current_name != self._canonical_manager_name():
            raise RuntimeError(self.strings("rebuild_forbidden"))
        new_name = self._validate_manager_rebuild_name(new_name)
        source = self._manager_rebuild_source_path().read_text(encoding="utf-8")
        rebuilt, replacements = self._replace_manager_name_literals(
            source,
            old_name=current_name,
            new_name=new_name,
        )
        if replacements <= 0:
            raise RuntimeError(self.strings("rebuild_no_replacements"))
        return rebuilt, replacements

    def _build_manager_rebuild_page(self) -> tuple[str, list]:
        C = self.C
        state = self._manager_rebuild_state()
        new_name = str(state.get("name") or "XPatchKernelManagerFork")
        delete_current = bool(state.get("delete_current", True))
        copy_config = bool(state.get("copy_config", True))
        force_wipe_current_config = bool(state.get("force_wipe_current_config", False))
        try:
            _, replacements = self._build_rebuilt_manager_source(new_name)
        except Exception:
            replacements = 0
        text = (
            f"{C['rebuild']} <b>{self.strings('rebuild_title')}</b>\n\n"
            f"<blockquote>{self.strings('rebuild_desc')}</blockquote>\n"
            f"{C['info']} {self.strings('rebuild_current_name')} <code>{html.escape(str(getattr(self, 'name', '')))}</code>\n"
            f"{C['file']} {self.strings('rebuild_new_name')} <code>{html.escape(new_name)}</code>\n"
            f"{C['reload']} {self.strings('rebuild_replacements')} <code>{replacements}</code>\n"
            f"{C['diskette']} {self.strings('rebuild_config_state')} <code>{self.strings('state_on' if copy_config else 'state_off')}</code>\n"
            f"{C['warning']} {self.strings('rebuild_delete_state')} <code>{self.strings('state_on' if delete_current else 'state_off')}</code>"
        )
        if delete_current and not copy_config:
            text += (
                f"\n{C['diskette']} {self.strings('rebuild_force_wipe_state')} "
                f"<code>{self.strings('state_on' if force_wipe_current_config else 'state_off')}</code>"
            )
        buttons = [
            [
                self.Button.input(
                    f"📝 {self.strings('btn_rebuild_name')}",
                    self.on_manager_rebuild_name_input,
                    placeholder=new_name,
                    ttl=600,
                    style="primary",
                ),
                self.Button.inline(
                    f"🎲 {self.strings('btn_rebuild_random')}",
                    self.on_manager_rebuild_random,
                    ttl=600,
                    style="primary",
                ),
            ],
            [
                self.Button.inline(
                    self.strings(
                        "btn_rebuild_copy_config"
                        if copy_config
                        else "btn_rebuild_skip_config"
                    ),
                    self.on_toggle_manager_rebuild_copy_config,
                    ttl=600,
                    style="success" if copy_config else "danger",
                )
            ],
        ]
        if delete_current and not copy_config:
            buttons.append(
                [
                    self.Button.inline(
                        self.strings(
                            "btn_rebuild_force_wipe"
                            if force_wipe_current_config
                            else "btn_rebuild_keep_current_cfg"
                        ),
                        self.on_toggle_manager_rebuild_force_wipe,
                        ttl=600,
                        style="danger" if force_wipe_current_config else "success",
                    )
                ]
            )
        buttons.extend(
            [
                [
                    self.Button.inline(
                        self.strings(
                            "btn_rebuild_delete_current"
                            if delete_current
                            else "btn_rebuild_keep_current"
                        ),
                        self.on_toggle_manager_rebuild_delete,
                        ttl=600,
                        style="danger" if delete_current else "success",
                    )
                ],
            ]
        )
        buttons.extend(
            [
                [
                    self.Button.inline(
                        f"📦 {self.strings('btn_rebuild_send')}",
                        self.on_manager_rebuild_send,
                        ttl=600,
                        style="success",
                    )
                ],
                [
                    self.Button.inline(
                        f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                        self.on_back_to_utils,
                        ttl=600,
                    )
                ],
            ]
        )
        return text, buttons

    def _build_utils_page(self) -> tuple[str, list]:
        C = self.C
        text = (
            f"{C['utils']} <b>{self.strings('utils_title')}</b>\n\n"
            f"<blockquote>{C['logs']} {self.strings('utils_logs_desc')}</blockquote>\n"
            f"<blockquote>{C['settings']} <b>{self.strings('btn_patch_system_module')}</b> — {self.strings('system_patch_desc')}</blockquote>\n"
            f"<blockquote>{C['rebuild']} {self.strings('utils_rebuild_desc')}</blockquote>\n"
            f"<blockquote>{C['warning']} {self.strings('utils_danger_desc')}</blockquote>"
        )
        buttons = [
            [
                self.Button.inline(
                    f"{self._clear_text(C['logs'])} {self.strings('btn_live_logs')}",
                    self.on_live_logs_menu,
                    ttl=600,
                )
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['settings'])} {self.strings('btn_patch_system_module')}",
                    self.on_system_patch_menu,
                    ttl=600,
                )
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['rebuild'])} {self.strings('btn_rebuild_manager')}",
                    self.on_manager_rebuild_menu,
                    ttl=600,
                )
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['delete'])} {self.strings('btn_remove_xkernel')}",
                    self.on_remove_xkernel_menu,
                    ttl=600,
                )
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                    self.on_back_to_main,
                    ttl=600,
                )
            ],
        ]
        return text, buttons

    def _build_system_patch_page(self) -> tuple[str, list]:
        C = self.C
        status = self._system_module_patch_status()
        text = (
            f"{C['settings']} <b>{self.strings('system_patch_title')}</b>\n\n"
            f"<blockquote>{self.strings('system_patch_desc')}</blockquote>"
        )
        if not status.get("available", False):
            text += f"\n<blockquote>{C['warning']} {html.escape(str(status.get('error', self.strings('system_patch_unsupported'))))}</blockquote>"
        buttons = [
            [
                self.Button.inline(
                    self.strings("btn_system_patch_man"),
                    self.on_system_patch_man_menu,
                    ttl=600,
                )
            ],
            [
                self.Button.inline(
                    self.strings("btn_system_patch_updates"),
                    self.on_system_patch_updates_menu,
                    ttl=600,
                )
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                    self.on_back_to_utils,
                    ttl=600,
                )
            ],
        ]
        return text, buttons

    def _build_system_patch_man_page(self) -> tuple[str, list]:
        C = self.C
        man_extera = bool(self._cfg("system_patch_man_extera", False))
        man_mcmac = bool(self._cfg("system_patch_man_mcmac", False))
        text = (
            f"{C['settings']} <b>{self.strings('system_patch_man_title')}</b>\n\n"
            f"<blockquote>{self.strings('system_patch_man_desc')}</blockquote>"
        )
        buttons = [
            [
                self.Button.inline(
                    self.strings(
                        "btn_system_patch_man_extera",
                        state=self.strings("state_on" if man_extera else "state_off"),
                    ),
                    self.on_toggle_system_patch_man_extera,
                    ttl=600,
                    style="success" if man_extera else "danger",
                )
            ],
            [
                self.Button.inline(
                    self.strings(
                        "btn_system_patch_man_mcmac",
                        state=self.strings("state_on" if man_mcmac else "state_off"),
                    ),
                    self.on_toggle_system_patch_man_mcmac,
                    ttl=600,
                    style="success" if man_mcmac else "danger",
                )
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                    self.on_system_patch_menu,
                    ttl=600,
                )
            ],
        ]
        return text, buttons

    def _build_system_patch_updates_page(self) -> tuple[str, list]:
        C = self.C
        enabled = bool(self._cfg("system_patch_updates_xkernel", False))
        text = (
            f"{C['settings']} <b>{self.strings('system_patch_updates_title')}</b>\n\n"
            f"<blockquote>{self.strings('system_patch_updates_desc')}</blockquote>"
        )
        buttons = [
            [
                self.Button.inline(
                    self.strings(
                        "btn_system_patch_updates_xkernel",
                        state=self.strings("state_on" if enabled else "state_off"),
                    ),
                    self.on_toggle_system_patch_updates_xkernel,
                    ttl=600,
                    style="success" if enabled else "danger",
                )
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                    self.on_system_patch_menu,
                    ttl=600,
                )
            ],
        ]
        return text, buttons

    @callback(ttl=600)
    async def on_system_patch_menu(self, call) -> None:
        text, buttons = self._build_system_patch_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_system_patch_man_menu(self, call) -> None:
        text, buttons = self._build_system_patch_man_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_system_patch_updates_menu(self, call) -> None:
        text, buttons = self._build_system_patch_updates_page()
        await call.edit(text, buttons=buttons)

    async def _toggle_system_patch_option(
        self, call: Any, key: str, builder: Any
    ) -> None:
        self.config[key] = not bool(self._cfg(key, False))
        ok = self._set_runtime_system_module_patches()
        await self._save_config()
        if not ok:
            await call.answer(self.strings("system_patch_unsupported"), alert=True)
        text, buttons = builder()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_toggle_system_patch_man_extera(self, call) -> None:
        await self._toggle_system_patch_option(
            call, "system_patch_man_extera", self._build_system_patch_man_page
        )

    @callback(ttl=600)
    async def on_toggle_system_patch_man_mcmac(self, call) -> None:
        await self._toggle_system_patch_option(
            call, "system_patch_man_mcmac", self._build_system_patch_man_page
        )

    @callback(ttl=600)
    async def on_toggle_system_patch_updates_xkernel(self, call) -> None:
        await self._toggle_system_patch_option(
            call, "system_patch_updates_xkernel", self._build_system_patch_updates_page
        )

    @callback(ttl=600)
    async def on_utils_menu(self, call) -> None:
        self._stop_live_logs()
        text, buttons = self._build_utils_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_back_to_utils(self, call) -> None:
        self._stop_live_logs()
        text, buttons = self._build_utils_page()
        await call.edit(text, buttons=buttons)

    @staticmethod
    def _event_chat_id(event: Any) -> Any:
        for attr in ("chat_id", "peer_id"):
            value = getattr(event, attr, None)
            if value is not None:
                return value
        message = getattr(event, "message", None)
        for attr in ("chat_id", "peer_id"):
            value = getattr(message, attr, None)
            if value is not None:
                return value
        return "me"

    def _user_client(self) -> Any:
        client = getattr(self, "client", None)
        if client is not None and callable(getattr(client, "send_file", None)):
            return client
        kernel = getattr(self, "kernel", None)
        client = getattr(kernel, "client", None)
        if client is not None and callable(getattr(client, "send_file", None)):
            return client
        raise RuntimeError("user client with send_file is not available")

    async def _forward_saved_rebuild_file(
        self,
        client: Any,
        saved_message: Any,
        chat_id: Any,
    ) -> bool:
        if chat_id in {None, "me"}:
            return False
        try:
            forward_to = getattr(saved_message, "forward_to", None)
            if callable(forward_to):
                result = forward_to(chat_id)
                if inspect.isawaitable(result):
                    await result
                return True
            forward_messages = getattr(client, "forward_messages", None)
            if callable(forward_messages):
                await forward_messages(chat_id, saved_message)
                return True
        except Exception as exc:
            self.log.debug("manager rebuild forward failed: %s", exc)
        return False

    async def _delete_saved_rebuild_file(self, client: Any, saved_message: Any) -> None:
        with contextlib.suppress(Exception):
            delete = getattr(saved_message, "delete", None)
            if callable(delete):
                result = delete()
                if inspect.isawaitable(result):
                    await result
                return
        with contextlib.suppress(Exception):
            delete_messages = getattr(client, "delete_messages", None)
            message_id = getattr(saved_message, "id", None)
            if callable(delete_messages) and message_id is not None:
                await delete_messages("me", [message_id])

    async def _copy_manager_rebuild_config(self, new_name: str) -> None:
        kernel = getattr(self, "kernel", None)
        save_config = getattr(kernel, "save_module_config", None)
        if callable(save_config):
            await save_config(new_name, self.config.to_dict())
        store_schema = getattr(kernel, "store_module_config_schema", None)
        if callable(store_schema):
            store_schema(new_name, self.config)

    async def _send_rebuilt_manager_file(
        self,
        event: Any,
        *,
        new_name: str,
        source: str,
        replacements: int,
    ) -> bool:
        chat_id = self._event_chat_id(event)
        client = self._user_client()
        file_name = f"{new_name}.py"
        caption = self.strings(
            "rebuild_sent",
            file=html.escape(file_name),
            count=replacements,
        )
        with tempfile.TemporaryDirectory(prefix="xpatch_manager_rebuild_") as tmp:
            path = Path(tmp) / file_name
            path.write_text(source, encoding="utf-8")
            saved_message = await client.send_file(
                "me",
                file=str(path),
                caption=caption,
                parse_mode="html",
                force_document=True,
            )
            if chat_id in {None, "me"}:
                return True
            forwarded = await self._forward_saved_rebuild_file(
                client, saved_message, chat_id
            )
            if forwarded:
                await self._delete_saved_rebuild_file(client, saved_message)
                return True
            return False

    async def _refresh_manager_rebuild_event(self) -> bool:
        call = getattr(self, "_manager_rebuild_event", None)
        if call is None:
            return False
        try:
            text, buttons = self._build_manager_rebuild_page()
            await call.edit(text, buttons=buttons)
            return True
        except Exception as exc:
            self.log.debug("cannot refresh manager rebuild menu: %s", exc)
            return False

    @callback(ttl=600)
    async def on_manager_rebuild_menu(self, call) -> None:
        self._manager_rebuild_event = call
        text, buttons = self._build_manager_rebuild_page()
        await call.edit(text, buttons=buttons)

    async def on_manager_rebuild_name_input(
        self,
        event: Any,
        text: str,
        data: Any = None,
    ) -> None:
        try:
            name = self._validate_manager_rebuild_name(text)
        except ValueError as exc:
            await self._refresh_manager_rebuild_event()
            with contextlib.suppress(Exception):
                await self._edit(event, f"🚫 {html.escape(str(exc))}")
            return
        state = self._manager_rebuild_state()
        state["name"] = name
        refreshed = await self._refresh_manager_rebuild_event()
        if not refreshed:
            with contextlib.suppress(Exception):
                await self._edit(
                    event,
                    f"{self.C['true']} {self.strings('rebuild_name_updated', name=html.escape(name))}",
                )

    @callback(ttl=600)
    async def on_manager_rebuild_random(self, call) -> None:
        self._manager_rebuild_event = call
        name = self._random_manager_rebuild_name()
        self._manager_rebuild_state()["name"] = name
        await call.answer(self.strings("rebuild_random_answer", name=name), alert=False)
        text, buttons = self._build_manager_rebuild_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_toggle_manager_rebuild_delete(self, call) -> None:
        self._manager_rebuild_event = call
        state = self._manager_rebuild_state()
        state["delete_current"] = not bool(state.get("delete_current", True))
        text, buttons = self._build_manager_rebuild_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_toggle_manager_rebuild_copy_config(self, call) -> None:
        self._manager_rebuild_event = call
        state = self._manager_rebuild_state()
        state["copy_config"] = not bool(state.get("copy_config", True))
        text, buttons = self._build_manager_rebuild_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_toggle_manager_rebuild_force_wipe(self, call) -> None:
        self._manager_rebuild_event = call
        state = self._manager_rebuild_state()
        state["force_wipe_current_config"] = not bool(
            state.get("force_wipe_current_config", False)
        )
        text, buttons = self._build_manager_rebuild_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_manager_rebuild_send(self, call) -> None:
        self._manager_rebuild_event = call
        state = self._manager_rebuild_state()
        new_name = str(state.get("name") or "")
        delete_current = bool(state.get("delete_current", True))
        copy_config = bool(state.get("copy_config", True))
        force_wipe_current_config = bool(state.get("force_wipe_current_config", False))
        try:
            source, replacements = self._build_rebuilt_manager_source(new_name)
            delivered = await self._send_rebuilt_manager_file(
                call,
                new_name=new_name,
                source=source,
                replacements=replacements,
            )
        except Exception as exc:
            self.log.exception("manager rebuild failed")
            await call.answer(self.strings("rebuild_send_failed"), alert=True)
            await call.edit(
                f"🚫 <b>{self.strings('rebuild_send_failed')}</b>\n"
                f"<blockquote><code>{html.escape(str(exc))}</code></blockquote>",
                buttons=[
                    [
                        self.Button.inline(
                            f"{self._clear_text(self.C['back'])} {self.strings('btn_back')}",
                            self.on_manager_rebuild_menu,
                            ttl=600,
                        )
                    ]
                ],
            )
            return

        if copy_config:
            await self._copy_manager_rebuild_config(new_name)

        if delete_current:
            if not delivered:
                await call.answer(
                    self.strings("rebuild_saved_only_no_delete"), alert=True
                )
                text, buttons = self._build_manager_rebuild_page()
                await call.edit(text, buttons=buttons)
                return
            await call.answer(self.strings("rebuild_sent_delete"), alert=True)
            delete_args = self.name
            if not copy_config and force_wipe_current_config:
                delete_args = f"{delete_args} -f"
            await self.invoke("um", args=delete_args, chat_id="me")
            return

        await call.answer(
            self.strings("rebuild_sent", file=f"{new_name}.py", count=replacements),
            alert=False,
        )
        text, buttons = self._build_manager_rebuild_page()
        await call.edit(text, buttons=buttons)

    def _xkernel_remove_options(self) -> dict[str, bool]:
        options = getattr(self, "_xkernel_remove_state", None)
        if not isinstance(options, dict):
            options = {
                "core": True,
                "backups": False,
                "manager": False,
                "patches": False,
                "default_standard": True,
                "restart": True,
            }
            self._xkernel_remove_state = options
        return options

    def _toggle_text(self, label: str, enabled: bool) -> str:
        state = self.strings("state_on" if enabled else "state_off")
        icon = self._clear_text(
            self.C.get("true", "✅") if enabled else self.C.get("off", "❌")
        )
        return f"{icon} {label}: {state}"

    def _build_remove_xkernel_page(self) -> tuple[str, list]:
        C = self.C
        options = self._xkernel_remove_options()
        text = (
            f"{C['warning']} <b>{self.strings('remove_title')}</b>\n\n"
            f"<blockquote>{self.strings('remove_desc')}</blockquote>"
        )
        buttons = [
            [
                self.Button.inline(
                    f"{self._clear_text(C['delete'])} {self.strings('btn_start_remove')}",
                    self.on_remove_xkernel_start,
                    ttl=300,
                )
            ],
            [
                self.Button.inline(
                    self._toggle_text(self.strings("remove_opt_core"), options["core"]),
                    self.on_toggle_remove_option,
                    data="core",
                    ttl=600,
                )
            ],
            [
                self.Button.inline(
                    self._toggle_text(
                        self.strings("remove_opt_backups"), options["backups"]
                    ),
                    self.on_toggle_remove_option,
                    data="backups",
                    ttl=600,
                )
            ],
            [
                self.Button.inline(
                    self._toggle_text(
                        self.strings("remove_opt_manager"), options["manager"]
                    ),
                    self.on_toggle_remove_option,
                    data="manager",
                    ttl=600,
                )
            ],
            [
                self.Button.inline(
                    self._toggle_text(
                        self.strings("remove_opt_patches"), options["patches"]
                    ),
                    self.on_toggle_remove_option,
                    data="patches",
                    ttl=600,
                )
            ],
            [
                self.Button.inline(
                    self._toggle_text(
                        self.strings("remove_opt_default"), options["default_standard"]
                    ),
                    self.on_toggle_remove_option,
                    data="default_standard",
                    ttl=600,
                )
            ],
            [
                self.Button.inline(
                    self._toggle_text(
                        self.strings("remove_opt_restart"), options["restart"]
                    ),
                    self.on_toggle_remove_option,
                    data="restart",
                    ttl=600,
                )
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                    self.on_back_to_utils,
                    ttl=600,
                )
            ],
        ]
        return text, buttons

    @callback(ttl=600)
    async def on_remove_xkernel_menu(self, call) -> None:
        self._stop_live_logs()
        self._xkernel_remove_options()
        text, buttons = self._build_remove_xkernel_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_toggle_remove_option(self, call, data: Any = None) -> None:
        options = self._xkernel_remove_options()
        key = str(data or "")
        if key in options:
            options[key] = not bool(options[key])
        text, buttons = self._build_remove_xkernel_page()
        await call.edit(text, buttons=buttons)

    def _patches_dir_path(self) -> Path:
        pm = self._get_pm()
        raw = getattr(pm, "patches_dir", "patches") if pm else "patches"
        path = Path(str(raw))
        return path if path.is_absolute() else self._repo_root() / path

    async def _execute_xkernel_removal(self, options: dict[str, bool]) -> list[str]:
        lines: list[str] = []

        if options.get("core", False):
            target = self._xkernel_path()
            if target.exists():
                target.unlink()
                lines.append(
                    self.strings("remove_core_deleted", path=html.escape(str(target)))
                )
            else:
                lines.append(self.strings("remove_core_absent"))

        if options.get("backups", False):
            backups = self._backup_files()
            for backup in backups:
                backup.unlink(missing_ok=True)
            lines.append(self.strings("remove_backups_deleted", count=len(backups)))

        if options.get("patches", False):
            patches_dir = self._patches_dir_path()
            if patches_dir.exists():
                shutil.rmtree(patches_dir)
                lines.append(
                    self.strings(
                        "remove_patches_deleted", path=html.escape(str(patches_dir))
                    )
                )
            else:
                lines.append(self.strings("remove_patches_absent"))

        if options.get("default_standard", False):
            self._set_default_core("standard")
            lines.append(self.strings("remove_default_standard"))

        if options.get("manager", False):
            await self.invoke("um", args=self.name, chat_id="me")
            lines.append(self.strings("remove_manager_requested"))

        if options.get("restart", False):
            await self.invoke("restart", chat_id="me")
            lines.append(self.strings("remove_restart_requested"))

        return lines or [self.strings("remove_nothing_selected")]

    @callback(ttl=300)
    async def on_remove_xkernel_start(self, call) -> None:
        options = dict(self._xkernel_remove_options())
        await call.answer(self.strings("remove_answer_start"), alert=False)
        try:
            lines = await self._execute_xkernel_removal(options)
        except Exception as exc:
            self.log.exception("XKernel removal failed")
            await call.edit(
                f"{self.C['off']} <b>{self.strings('remove_failed_title')}</b>\n\n"
                f"<blockquote><code>{html.escape(str(exc))}</code></blockquote>",
                buttons=[
                    [
                        self.Button.inline(
                            f"{self._clear_text(self.C['back'])} {self.strings('btn_back')}",
                            self.on_remove_xkernel_menu,
                            ttl=600,
                        )
                    ]
                ],
            )
            return

        await call.edit(
            f"{self.C['true']} <b>{self.strings('remove_done_title')}</b>\n\n<blockquote>"
            + "\n".join(lines)
            + "</blockquote>",
            buttons=[
                [
                    self.Button.inline(
                        f"{self._clear_text(self.C['back'])} {self.strings('btn_back')}",
                        self.on_utils_menu,
                        ttl=600,
                    )
                ]
            ],
        )

    @callback(ttl=600)
    async def on_live_logs_menu(self, call) -> None:
        self._live_logs_event = call
        text, buttons = await self._build_live_logs_page()
        await call.edit(text, buttons=buttons)
        self._ensure_live_logs_task()

    @staticmethod
    def _next_choice(current: int, choices: tuple[int, ...]) -> int:
        try:
            index = choices.index(current)
        except ValueError:
            return choices[0]
        return choices[(index + 1) % len(choices)]

    def _next_live_logs_max_lines(self, current: int | None = None) -> int:
        value = self._live_logs_max_lines() if current is None else current
        return self._next_choice(value, (5, 10, 20, 25))

    def _next_live_logs_refresh_interval(self, current: int | None = None) -> int:
        value = self._live_logs_refresh_interval() if current is None else current
        return self._next_choice(value, (5, 10, 15))

    def _notification_delay_seconds(self) -> int:
        try:
            value = int(self._cfg("update_notification_delay", 0) or 0)
        except (TypeError, ValueError):
            return 0
        return value if value in {0, 30, 60, 300} else 0

    def _next_notification_delay_seconds(self) -> int:
        return self._next_choice(self._notification_delay_seconds(), (0, 30, 60, 300))

    async def _set_live_logs_max_lines(self, call: Any, value: int) -> None:
        self.config["live_logs_max_lines"] = str(value)
        await self._save_config()
        await call.answer(self.strings("logs_lines_answer", value=value), alert=False)
        self._live_logs_event = call
        await self._refresh_live_logs()

    async def _set_live_logs_refresh_interval(self, call: Any, value: int) -> None:
        self.config["live_logs_refresh_interval"] = str(value)
        await self._save_config()
        await call.answer(
            self.strings("logs_interval_answer", value=value), alert=False
        )
        self._live_logs_event = call
        await self._refresh_live_logs()

    @callback(ttl=600)
    async def on_cycle_live_logs_lines(self, call) -> None:
        await self._set_live_logs_max_lines(
            call,
            self._next_live_logs_max_lines(),
        )

    @callback(ttl=600)
    async def on_cycle_live_logs_interval(self, call) -> None:
        await self._set_live_logs_refresh_interval(
            call,
            self._next_live_logs_refresh_interval(),
        )

    def _build_settings_page(self) -> tuple[str, list]:
        C = self.C
        stealth = bool(self._cfg("stealth_mode", False))
        auto_update = bool(self._cfg("auto_update_kernel", False))
        notifications = bool(self._cfg("update_notifications", True))
        text = (
            f"{C['settings']} <b>{self.strings('settings_title')}</b>\n\n"
            f"{self._bool_icon(stealth)} <b>{self.strings('settings_stealth')}</b>\n"
            f"<blockquote><em>{C['бууу']} {self.strings('settings_stealth_desc')}</em></blockquote>\n"
            f"{self._bool_icon(auto_update)} <b>{self.strings('settings_auto')}</b>\n"
            f"<blockquote><em>{C['info']} {self.strings('settings_auto_desc')}</em></blockquote>\n"
            f"{self._bool_icon(notifications)} <b>{self.strings('settings_notify')}</b>\n"
            f"<blockquote><em>{C['diskette']} {self.strings('settings_notify_desc')}</em></blockquote>"
        )
        buttons = [
            [
                self.Button.inline(
                    self.strings(
                        "settings_toggle_stealth",
                        state=self.strings("state_on" if stealth else "state_off"),
                    ),
                    self.on_toggle_stealth,
                    ttl=600,
                    style="danger" if not stealth else "success",
                )
            ],
            [
                self.Button.inline(
                    self.strings(
                        "settings_toggle_auto",
                        state=self.strings("state_on" if auto_update else "state_off"),
                    ),
                    self.on_toggle_auto_update,
                    ttl=600,
                    style="danger" if not auto_update else "success",
                )
            ],
            [
                self.Button.inline(
                    self.strings(
                        "settings_toggle_notify",
                        state=self.strings(
                            "state_on" if notifications else "state_off"
                        ),
                    ),
                    self.on_toggle_notifications,
                    ttl=600,
                    style="danger" if not notifications else "success",
                ),
                *(
                    [
                        self.Button.inline(
                            f"{self._clear_text(C['settings'])} {self.strings('btn_notify_settings')}",
                            self.on_notify_settings_menu,
                            ttl=600,
                            style="primary",
                        )
                    ]
                    if notifications
                    else []
                ),
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['magic'] if self._get_pm() is not None else C['warning'])} {self.strings('btn_experimental')}",
                    self.on_experimental_settings_menu,
                    ttl=600,
                    style="primary" if self._get_pm() is not None else "danger",
                )
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                    self.on_back_to_main,
                    ttl=600,
                )
            ],
        ]
        return text, buttons

    def _bool_icon(self, value: bool) -> str:
        return self.C["on"] if value else self.C["off"]

    @callback(ttl=600)
    async def on_settings_menu(self, call) -> None:
        text, buttons = self._build_settings_page()
        await call.edit(text, buttons=buttons)

    def _build_notify_settings_page(self) -> tuple[str, list]:
        C = self.C
        notify_delay = self._notification_delay_seconds()
        next_notify_delay = self._next_notification_delay_seconds()
        manager_notifications = bool(self._cfg("manager_update_notifications", True))
        text = (
            f"{C['diskette']} <b>{self.strings('notify_settings_title')}</b>\n\n"
            f"<blockquote><em>{self.strings('settings_notify_desc')}\n"
            f"{self.strings('settings_notify_state', delay=notify_delay, manager=self.strings('state_on' if manager_notifications else 'state_off'))}</em></blockquote>"
        )
        buttons = [
            [
                self.Button.inline(
                    self.strings(
                        "settings_notify_delay_button",
                        delay=notify_delay,
                        next_delay=next_notify_delay,
                    ),
                    self.on_cycle_notification_delay,
                    ttl=600,
                    style="primary",
                )
            ],
            [
                self.Button.inline(
                    self.strings(
                        "settings_notify_manager_toggle",
                        state=self.strings(
                            "state_on" if manager_notifications else "state_off"
                        ),
                    ),
                    self.on_toggle_manager_update_notifications,
                    ttl=600,
                    style="danger" if not manager_notifications else "success",
                )
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                    self.on_settings_menu,
                    ttl=600,
                )
            ],
        ]
        return text, buttons

    @callback(ttl=600)
    async def on_notify_settings_menu(self, call) -> None:
        text, buttons = self._build_notify_settings_page()
        await call.edit(text, buttons=buttons)

    def _build_extera_proxy_page(self) -> tuple[str, list]:
        C = self.C
        supported = self._get_pm() is not None
        all_enabled = bool(self._cfg("extera_proxy_all", False))
        modules = self._extera_modules_from_config()
        modules_text = ", ".join(html.escape(item) for item in modules) or self.strings(
            "none"
        )
        scopes = self._extera_scopes_from_config()
        root_enabled = "root" in scopes
        scopes_text = (
            self._extera_proxy_scopes_label()
            if supported
            else self.strings("no_access")
        )
        modules_label = self.strings(
            "extera_modules_excluded" if all_enabled else "extera_modules_selected"
        )
        status = html.escape(
            self._extera_proxy_status_label()
            if supported
            else self.strings("status_not_supported")
        )
        status_icon = C["moon"] if supported else C["warning"]
        text = (
            f"{C['injection']} <b>{self.strings('extera_title')}</b>\n"
            f"<blockquote>{C['info']} {self.strings('extera_desc')}</blockquote>\n"
            f"<blockquote>{C['warning']} {self.strings('extera_do_not_touch')}</blockquote>\n"
            f"{status_icon} {self.strings('extera_status_label')} <b>{status}</b>\n"
            f"{C['command']} <b>{self.strings('extera_scopes_label')}</b> <code>{html.escape(scopes_text)}</code>\n"
            f"{C['info']} {modules_label}: <code>{modules_text}</code>\n"
            f"<blockquote expandable>{C['warning']} <b>{self.strings('extera_trusted_warning')}</b></blockquote>"
        )
        if not supported:
            return text, [
                [
                    self.Button.inline(
                        f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                        self.on_experimental_settings_menu,
                        ttl=600,
                    )
                ]
            ]
        buttons = [
            [
                self.Button.inline(
                    self.strings(
                        "btn_extera_all",
                        state=self.strings("state_on" if all_enabled else "state_off"),
                    ),
                    self.on_toggle_extera_proxy_all,
                    ttl=600,
                    style="danger" if not all_enabled else "success",
                )
            ],
            (
                [
                    self.Button.inline(
                        self.strings("btn_extera_root_custom"),
                        self.on_toggle_extera_scope_root,
                        ttl=600,
                        style="success",
                    )
                ]
                if root_enabled
                else [
                    self.Button.inline(
                        self.strings(
                            "btn_extera_scope",
                            scope="Kernel",
                            state=self.strings(
                                "state_on" if "kernel" in scopes else "state_off"
                            ),
                        ),
                        self.on_toggle_extera_scope_kernel,
                        ttl=600,
                        style="danger" if not "kernel" in scopes else "success",
                    ),
                    self.Button.inline(
                        self.strings(
                            "btn_extera_scope",
                            scope="Client",
                            state=self.strings(
                                "state_on" if "client" in scopes else "state_off"
                            ),
                        ),
                        self.on_toggle_extera_scope_client,
                        ttl=600,
                        style="danger" if not "client" in scopes else "success",
                    ),
                    self.Button.inline(
                        self.strings(
                            "btn_extera_scope",
                            scope="Event",
                            state=self.strings(
                                "state_on" if "event" in scopes else "state_off"
                            ),
                        ),
                        self.on_toggle_extera_scope_event,
                        ttl=600,
                        style="danger" if not "event" in scopes else "success",
                    ),
                ]
            ),
            [
                self.Button.input(
                    f"{self._clear_text(C['add'])} {self.strings('btn_extera_add_module')}",
                    self.on_extera_proxy_add_input,
                    placeholder="ModuleName",
                    ttl=600,
                    style="success",
                ),
                self.Button.input(
                    f"{self._clear_text(C['delete'])} {self.strings('btn_extera_remove_module')}",
                    self.on_extera_proxy_remove_input,
                    placeholder="ModuleName",
                    ttl=600,
                    style="danger",
                ),
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['delete'])} {self.strings('btn_extera_clear_list')}",
                    self.on_clear_extera_proxy_modules,
                    ttl=600,
                )
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['magic'])} {self.strings('btn_extera_extra_features')}",
                    self.on_mcmac_settings_menu,
                    ttl=600,
                    style="primary",
                )
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                    self.on_experimental_settings_menu,
                    ttl=600,
                )
            ],
        ]
        return text, buttons

    async def _refresh_extera_proxy_event(self) -> bool:
        call = getattr(self, "_extera_proxy_event", None)
        if call is None:
            return False
        try:
            text, buttons = self._build_extera_proxy_page()
            await call.edit(text, buttons=buttons)
            return True
        except Exception as exc:
            self.log.debug("cannot refresh ExteraProxy menu: %s", exc)
            return False

    @callback(ttl=600)
    async def on_extera_proxy_menu(self, call) -> None:
        self._extera_proxy_event = call
        text, buttons = self._build_extera_proxy_page()
        await call.edit(text, buttons=buttons)

    def _build_mcmac_settings_page(self) -> tuple[str, list]:
        C = self.C
        status = self._mcmac_status()
        enabled = bool(status.get("enabled", self._cfg("mcmac_enabled", False)))
        mode = str(status.get("mode") or self._cfg("mcmac_mode", "permissive"))
        audit_mode = str(
            status.get("audit_mode") or self._cfg("mcmac_audit_mode", "all") or "all"
        )
        available = bool(status.get("available", False))
        path = html.escape(str(status.get("path", "")))
        error = html.escape(str(status.get("error", "")))
        audit_allowed = int(status.get("audit_allowed", 0) or 0)
        audit_denied = int(status.get("audit_denied", 0) or 0)
        audit_blocked = int(status.get("audit_blocked", 0) or 0)
        audit_dropped = int(status.get("audit_dropped", 0) or 0)
        contexts = status.get("contexts") or {}
        if isinstance(contexts, dict) and contexts:
            contexts_text = ", ".join(
                f"{html.escape(str(name))}:<code>{html.escape(str(kind))}</code>"
                for name, kind in sorted(contexts.items())
            )
        else:
            contexts_text = self.strings("none")
        text = (
            f"{C['lock']} <b>{self.strings('mcmac_title')}</b>\n\n"
            f"<blockquote>{self.strings('mcmac_desc')}</blockquote>\n"
            f"<blockquote>{self.strings('mcmac_mode_desc')}</blockquote>\n"
            f"<blockquote>{self.strings('mcmac_type_system_desc')}</blockquote>\n"
            f"<blockquote>{self.strings('mcmac_type_trusted_desc')}</blockquote>\n"
            f"<blockquote>{self.strings('mcmac_type_standard_desc')}</blockquote>\n"
            f"<blockquote>{self.strings('mcmac_type_untrusted_desc')}</blockquote>\n"
            f"<blockquote>{self.strings('mcmac_type_quarantine_desc')}</blockquote>\n"
            f"{self._bool_icon(enabled)} {self.strings('mcmac_enabled')} <code>{self.strings('state_on' if enabled else 'state_off')}</code>\n"
            f"{C['settings']} {self.strings('mcmac_mode')} <code>{html.escape(mode)}</code>\n"
            f"{C['lock']} {self.strings('mcmac_audit_mode')} <code>{html.escape(audit_mode)}</code>\n"
            f"{C['menu']} {self.strings('mcmac_audit_stats', allowed=audit_allowed, denied=audit_denied, blocked=audit_blocked, dropped=audit_dropped)}\n"
            f"{C['dir']} {self.strings('mcmac_path')} <code>{path}</code>\n"
            f"{C['menu']} {self.strings('mcmac_contexts')} {contexts_text}"
        )
        if not available:
            text += f"\n<blockquote>{C['warning']} {self.strings('mcmac_unavailable_warning')}</blockquote>"
        if error:
            text += (
                f"\n{C['warning']} {self.strings('mcmac_error')} <code>{error}</code>"
            )
        buttons = []
        if available:
            buttons.append(
                [
                    self.Button.inline(
                        self.strings(
                            "btn_mcmac_toggle",
                            state=self.strings("state_on" if enabled else "state_off"),
                        ),
                        self.on_toggle_mcmac_enabled,
                        ttl=600,
                        style="success" if enabled else "danger",
                    )
                ]
            )
        if available and enabled:
            buttons.extend(
                [
                    [
                        self.Button.inline(
                            self.strings("btn_mcmac_mode", mode=mode),
                            self.on_toggle_mcmac_mode,
                            ttl=600,
                            style="primary",
                        )
                    ],
                    [
                        self.Button.inline(
                            self.strings("btn_mcmac_audit_mode", mode=audit_mode),
                            self.on_mcmac_audit_mode_menu,
                            ttl=600,
                            style="primary",
                        )
                    ],
                    [
                        self.Button.input(
                            self.strings("btn_mcmac_set_module_type"),
                            self.on_mcmac_module_type_input,
                            placeholder="ModuleName:trusted",
                            ttl=600,
                            style="primary",
                        ),
                        self.Button.inline(
                            self.strings("btn_mcmac_remove_module_type"),
                            self.on_mcmac_module_type_remove_menu,
                            ttl=600,
                            style="danger",
                        ),
                    ],
                ]
            )
        buttons.extend(
            [
                [
                    self.Button.inline(
                        f"{self._clear_text(C['reload'])} {self.strings('btn_mcmac_update_libs')}",
                        self.on_refresh_mcmac_runtime,
                        ttl=600,
                        style="primary",
                    )
                ],
                [
                    self.Button.inline(
                        f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                        self.on_extera_proxy_menu,
                        ttl=600,
                    )
                ],
            ]
        )
        return text, buttons

    def _build_mcmac_audit_mode_page(self) -> tuple[str, list]:
        C = self.C
        status = self._mcmac_status()
        current = str(
            status.get("audit_mode") or self._cfg("mcmac_audit_mode", "all") or "all"
        ).casefold()
        audit_allowed = int(status.get("audit_allowed", 0) or 0)
        audit_denied = int(status.get("audit_denied", 0) or 0)
        audit_blocked = int(status.get("audit_blocked", 0) or 0)
        audit_dropped = int(status.get("audit_dropped", 0) or 0)
        modes = (
            ("all", "btn_mcmac_audit_all"),
            ("denied", "btn_mcmac_audit_denied"),
            ("blocked", "btn_mcmac_audit_blocked"),
            ("off", "btn_mcmac_audit_off"),
        )
        text = (
            f"{C['lock']} <b>{self.strings('mcmac_audit_mode_title')}</b>\n\n"
            f"<blockquote>{self.strings('mcmac_audit_mode_desc')}</blockquote>\n"
            f"{C['settings']} {self.strings('mcmac_audit_mode')} <code>{html.escape(current)}</code>\n"
            f"{C['menu']} {self.strings('mcmac_audit_stats', allowed=audit_allowed, denied=audit_denied, blocked=audit_blocked, dropped=audit_dropped)}"
        )
        buttons = [
            [
                self.Button.inline(
                    f"{'✅ ' if mode == current else ''}{self.strings(label)}",
                    self.on_set_mcmac_audit_mode,
                    data=mode,
                    ttl=600,
                    style="success" if mode == current else "primary",
                )
            ]
            for mode, label in modes
        ]
        buttons.append(
            [
                self.Button.inline(
                    f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                    self.on_mcmac_settings_menu,
                    ttl=600,
                )
            ]
        )
        return text, buttons

    def _mcmac_module_type_overrides(self) -> dict[str, str]:
        overrides = self._mcmac_module_types_config()
        contexts = self._mcmac_status().get("contexts") or {}
        if isinstance(contexts, dict):
            for module_name, security_type in contexts.items():
                module = str(module_name or "").strip()
                value = str(security_type or "").strip().casefold()
                if module and value:
                    overrides.setdefault(module, value)
        return dict(sorted(overrides.items(), key=lambda item: item[0].casefold()))

    def _build_mcmac_module_type_remove_page(
        self, page: int = 0
    ) -> tuple[str, list]:
        C = self.C
        page_size = 8
        overrides = self._mcmac_module_type_overrides()
        items = list(overrides.items())
        pages = max(1, (len(items) + page_size - 1) // page_size)
        page = max(0, min(int(page or 0), pages - 1))
        start = page * page_size
        page_items = items[start : start + page_size]

        if page_items:
            list_text = "\n".join(
                f"<code>{html.escape(module)}</code>: <code>{html.escape(security_type)}</code>"
                for module, security_type in page_items
            )
        else:
            list_text = self.strings("mcmac_remove_module_type_empty")

        text = (
            f"{C['lock']} <b>{self.strings('mcmac_remove_module_type_title')}</b>\n\n"
            f"{self.strings('mcmac_remove_module_type_desc')}\n\n"
            f"<blockquote>{list_text}</blockquote>\n"
            f"{C['menu']} {self.strings('mcmac_remove_module_type_page', page=page + 1, pages=pages)}"
        )
        buttons = [
            [
                self.Button.inline(
                    f"❌ {module}",
                    self.on_mcmac_module_type_remove_choice,
                    data={"module": module, "page": page},
                    ttl=600,
                    style="danger",
                )
            ]
            for module, _ in page_items
        ]
        if pages > 1:
            nav = []
            if page > 0:
                nav.append(
                    self.Button.inline(
                        self.strings("btn_mcmac_prev_page"),
                        self.on_mcmac_module_type_remove_menu,
                        data=page - 1,
                        ttl=600,
                    )
                )
            if page < pages - 1:
                nav.append(
                    self.Button.inline(
                        self.strings("btn_mcmac_next_page"),
                        self.on_mcmac_module_type_remove_menu,
                        data=page + 1,
                        ttl=600,
                    )
                )
            if nav:
                buttons.append(nav)
        buttons.append(
            [
                self.Button.inline(
                    f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                    self.on_mcmac_settings_menu,
                    ttl=600,
                )
            ]
        )
        return text, buttons

    @callback(ttl=600)
    async def on_mcmac_settings_menu(self, call) -> None:
        self._mcmac_settings_event = call
        text, buttons = self._build_mcmac_settings_page()
        await call.edit(text, buttons=buttons)

    async def _refresh_mcmac_settings_event(self) -> bool:
        call = getattr(self, "_mcmac_settings_event", None)
        if call is None:
            return False
        try:
            text, buttons = self._build_mcmac_settings_page()
            await call.edit(text, buttons=buttons)
            return True
        except Exception as exc:
            self.log.debug("cannot refresh MCMAC settings menu: %s", exc)
            return False

    @callback(ttl=600)
    async def on_toggle_mcmac_enabled(self, call) -> None:
        new_value = not bool(self._cfg("mcmac_enabled", False))
        self.config["mcmac_enabled"] = new_value
        ok = self._set_runtime_mcmac_enabled(new_value)
        await self._save_config()
        await call.answer(
            self.strings(
                "mcmac_enabled_answer" if new_value else "mcmac_disabled_answer"
            ),
            alert=not ok,
        )
        text, buttons = self._build_mcmac_settings_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_toggle_mcmac_mode(self, call) -> None:
        current = str(self._cfg("mcmac_mode", "permissive") or "permissive")
        new_mode = "enforcing" if current != "enforcing" else "permissive"
        self.config["mcmac_mode"] = new_mode
        ok = self._set_runtime_mcmac_mode(new_mode)
        await self._save_config()
        await call.answer(
            self.strings("mcmac_mode_answer", mode=new_mode),
            alert=not ok,
        )
        text, buttons = self._build_mcmac_settings_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_mcmac_audit_mode_menu(self, call) -> None:
        self._mcmac_settings_event = call
        text, buttons = self._build_mcmac_audit_mode_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_set_mcmac_audit_mode(self, call, data: Any = None) -> None:
        audit_mode = str(data or "all").strip().casefold()
        if audit_mode not in {"all", "denied", "blocked", "off"}:
            audit_mode = "all"
        self.config["mcmac_audit_mode"] = audit_mode
        ok = self._set_runtime_mcmac_audit_mode(audit_mode)
        await self._save_config()
        await call.answer(
            self.strings("mcmac_audit_mode_answer", mode=audit_mode),
            alert=not ok,
        )
        text, buttons = self._build_mcmac_audit_mode_page()
        await call.edit(text, buttons=buttons)

    async def on_mcmac_module_type_input(
        self,
        event: Any,
        text: str,
        data: Any = None,
    ) -> None:
        raw = str(text or "").strip()
        if ":" not in raw:
            await self._edit(event, f"🚫 {self.strings('mcmac_module_type_invalid')}")
            return
        module_name, security_type = [part.strip() for part in raw.split(":", 1)]
        security_type = security_type.casefold()
        if not module_name or security_type not in {
            "trusted",
            "standard",
            "untrusted",
            "quarantine",
        }:
            await self._edit(event, f"🚫 {self.strings('mcmac_module_type_invalid')}")
            return
        ok = self._set_runtime_mcmac_module_type(module_name, security_type)
        if ok:
            module_types = self._mcmac_module_types_config()
            module_types[module_name] = security_type
            await self._save_mcmac_module_types_config(module_types)
        await self._refresh_mcmac_settings_event()
        await self._edit(
            event,
            (
                f"{self.C['true']} "
                f"{self.strings('mcmac_module_type_updated', module=html.escape(module_name), type=security_type)}"
                if ok
                else f"🚫 {self.strings('unsupported_current_kernel')}"
            ),
        )

    @callback(ttl=600)
    async def on_mcmac_module_type_remove_menu(
        self, call, data: Any = None
    ) -> None:
        self._mcmac_settings_event = call
        try:
            page = int(data or 0)
        except (TypeError, ValueError):
            page = 0
        text, buttons = self._build_mcmac_module_type_remove_page(page)
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_mcmac_module_type_remove_choice(
        self, call, data: Any = None
    ) -> None:
        if isinstance(data, dict):
            module_name = str(data.get("module") or "").strip()
            page = int(data.get("page") or 0)
        else:
            module_name = str(data or "").strip()
            page = 0
        if not module_name:
            await call.answer(self.strings("mcmac_module_type_invalid"), alert=True)
            return
        ok = self._clear_runtime_mcmac_module_type(module_name)
        if ok:
            module_types = self._mcmac_module_types_config()
            module_types.pop(module_name, None)
            await self._save_mcmac_module_types_config(module_types)
        await call.answer(
            self._clear_text(
                self.strings("mcmac_module_type_removed", module=module_name)
                if ok
                else self.strings("unsupported_current_kernel")
            ),
            alert=not ok,
        )
        text, buttons = self._build_mcmac_module_type_remove_page(page)
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_refresh_mcmac_runtime(self, call) -> None:
        ok = await self._refresh_mcmac_runtime()
        if ok:
            self._apply_mcmac_from_config()
        await call.answer(
            self.strings("mcmac_refresh_ok" if ok else "mcmac_refresh_failed"),
            alert=not ok,
        )
        text, buttons = self._build_mcmac_settings_page()
        await call.edit(text, buttons=buttons)

    def _build_client_patch_page(self) -> tuple[str, list]:
        C = self.C
        supported = self._client_patch_supported()
        enabled = self._is_client_patch_enabled()
        options = self._client_patch_options_from_config()
        status = html.escape(self._client_patch_status_label())

        def value_line(label: str, key: str) -> str:
            value = options.get(key) or "—"
            return f"{C['info']} <b>{label}:</b> <code>{html.escape(value)}</code>"

        text = (
            f"{C['phone']} <b>{self.strings('client_title')}</b>\n"
            f"<blockquote>{C['info']} {self.strings('client_desc')}</blockquote>\n"
            f"<blockquote>{C['warning']} {self.strings('client_restart_warn')}</blockquote>\n"
            f"{self._bool_icon(enabled and supported)} {self.strings('client_status')} <b>{status}</b>\n"
            f"{value_line(self.strings('client_field_app_version'), 'app_version')}\n"
            f"{value_line(self.strings('client_field_device_model'), 'device_model')}\n"
            f"{value_line(self.strings('client_field_system_version'), 'system_version')}\n"
            f"{value_line(self.strings('client_field_lang_code'), 'lang_code')}\n"
            f"{value_line(self.strings('client_field_system_lang_code'), 'system_lang_code')}"
        )
        if not supported:
            return text, [
                [
                    self.Button.inline(
                        f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                        self.on_experimental_settings_menu,
                        ttl=600,
                    )
                ]
            ]

        buttons = [
            [
                self.Button.inline(
                    self.strings(
                        "btn_client_patch_toggle",
                        state=self.strings("state_on" if enabled else "state_off"),
                    ),
                    self.on_toggle_client_patch,
                    ttl=600,
                    style="success" if enabled else "danger",
                )
            ],
            [
                self.Button.input(
                    f"📝 {self.strings('btn_client_app_version')}",
                    self.on_client_patch_app_version_input,
                    placeholder="XClient 1.0",
                    ttl=600,
                ),
                self.Button.input(
                    f"{self._clear_text(C['phone'])} {self.strings('btn_client_device_model')}",
                    self.on_client_patch_device_model_input,
                    placeholder="XPhone",
                    ttl=600,
                ),
            ],
            [
                self.Button.input(
                    f"💿 {self.strings('btn_client_system_version')}",
                    self.on_client_patch_system_version_input,
                    placeholder="XOS 1",
                    ttl=600,
                ),
                self.Button.input(
                    f"🌐 {self.strings('btn_client_lang_code')}",
                    self.on_client_patch_lang_code_input,
                    placeholder="en",
                    ttl=600,
                ),
            ],
            [
                self.Button.input(
                    f"🌍 {self.strings('btn_client_system_lang_code')}",
                    self.on_client_patch_system_lang_code_input,
                    placeholder="en-US",
                    ttl=600,
                )
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['delete'])} {self.strings('btn_clear_params')}",
                    self.on_clear_client_patch_options,
                    ttl=600,
                )
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                    self.on_experimental_settings_menu,
                    ttl=600,
                )
            ],
        ]
        return text, buttons

    async def _refresh_client_patch_event(self) -> bool:
        call = getattr(self, "_client_patch_event", None)
        if call is None:
            return False
        try:
            text, buttons = self._build_client_patch_page()
            await call.edit(text, buttons=buttons)
            return True
        except Exception as exc:
            self.log.debug("cannot refresh Client Patch menu: %s", exc)
            return False

    @callback(ttl=600)
    async def on_client_patch_menu(self, call) -> None:
        self._client_patch_event = call
        text, buttons = self._build_client_patch_page()
        await call.edit(text, buttons=buttons)

    def _build_experimental_settings_page(self) -> tuple[str, list]:
        C = self.C
        patch_events = bool(self._cfg("experimental_patch_events", False))
        hot_reload = bool(self._cfg("experimental_patch_hot_reload", False))
        client_patch_enabled = self._is_client_patch_enabled()
        text = (
            f"{C['magic']} <b>{self.strings('experimental_title')}</b>\n\n"
            f"{self._bool_icon(patch_events)} <b>Patch events</b>\n"
            f"<blockquote><em>{C['injection']} {self.strings('experimental_events_desc')}</em></blockquote>\n"
            f"{self._bool_icon(hot_reload)} <b>{self.strings('experimental_hot_reload_title')}</b>\n"
            f"<blockquote><em>{C['reload']} {self.strings('experimental_hot_reload_desc')}</em></blockquote>\n"
            f"<blockquote>{C['warning']} <i>{self.strings('experimental_warning')}</i></blockquote>"
        )
        buttons = [
            [
                self.Button.inline(
                    self.strings(
                        "btn_patch_events",
                        state=self.strings("state_on" if patch_events else "state_off"),
                    ),
                    self.on_toggle_patch_events,
                    ttl=600,
                    style="danger" if not patch_events else "success",
                )
            ],
            [
                self.Button.inline(
                    self.strings(
                        "btn_hot_reload",
                        state=self.strings("state_on" if hot_reload else "state_off"),
                    ),
                    self.on_toggle_patch_hot_reload,
                    ttl=600,
                    style="danger" if not hot_reload else "success",
                ),
                *(
                    [
                        self.Button.inline(
                            f"{self._clear_text(C['settings'])} {self.strings('btn_hot_reload_settings')}",
                            self.on_hot_reload_settings_menu,
                            ttl=600,
                            style="primary",
                        )
                    ]
                    if hot_reload
                    else []
                ),
            ],
            [
                self.Button.inline(
                    f"{self.strings('btn_extera_clear_list')}",
                    self.on_clear_extera_proxy_modules_quick,
                    ttl=600,
                    style="danger",
                ),
                self.Button.inline(
                    f"{self._clear_text(C['injection'])} {self.strings('btn_extera_proxy')}",
                    self.on_extera_proxy_menu,
                    ttl=600,
                    style="primary",
                ),
            ],
            [
                self.Button.inline(
                    self.strings(
                        "btn_client_patch_quick_toggle",
                        state=self.strings(
                            "state_on" if client_patch_enabled else "state_off"
                        ),
                    ),
                    self.on_toggle_client_patch_quick,
                    ttl=600,
                    style="success" if client_patch_enabled else "danger",
                ),
                *(
                    [
                        self.Button.inline(
                            f"{self._clear_text(C['phone'])} {self.strings('btn_client_patch')}",
                            self.on_client_patch_menu,
                            ttl=600,
                            style=(
                                "primary"
                                if self._client_patch_supported()
                                else "danger"
                            ),
                        )
                    ]
                    if client_patch_enabled
                    else []
                ),
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                    self.on_settings_menu,
                    ttl=600,
                )
            ],
        ]
        return text, buttons

    def _build_hot_reload_settings_page(self) -> tuple[str, list]:
        C = self.C
        hot_reload_smart_disable = bool(
            self._cfg("experimental_hot_reload_smart_disable", False)
        )
        hot_reload_disable_on_first_fail = bool(
            self._cfg("experimental_hot_reload_disable_on_first_fail", False)
        )
        hot_load_new_patches = bool(
            self._cfg("experimental_hot_load_new_patches", False)
        )
        hot_reload_retry_interval = self._hot_reload_retry_interval()
        text = f"{C['reload']} <b>{self.strings('hot_reload_settings_title')}</b>\n\n"
        if not hot_reload_disable_on_first_fail:
            text += (
                f"<blockquote>{self.strings('hot_reload_smart_disable_desc')}</blockquote>\n"
                f"<blockquote>{self.strings('hot_reload_retry_interval_desc')}</blockquote>\n"
            )
        text += (
            f"<blockquote>{self.strings('hot_reload_disable_on_first_fail_desc')}</blockquote>\n"
            f"<blockquote>{self.strings('hot_load_new_patches_desc')}</blockquote>"
        )
        if not self._hot_reload_advanced_supported():
            text += (
                f"\n\n<blockquote>{C['warning']} "
                f"{self.strings('hot_reload_old_core_warning')}</blockquote>"
            )
        buttons = []
        if not hot_reload_disable_on_first_fail:
            buttons.append(
                [
                    self.Button.inline(
                        self.strings(
                            "btn_hot_reload_smart_disable",
                            state=self.strings(
                                "state_on" if hot_reload_smart_disable else "state_off"
                            ),
                        ),
                        self.on_toggle_hot_reload_smart_disable,
                        ttl=600,
                        style="success" if hot_reload_smart_disable else "danger",
                    ),
                    self.Button.input(
                        self.strings(
                            "btn_hot_reload_retry_interval",
                            interval=hot_reload_retry_interval,
                        ),
                        self.on_hot_reload_retry_interval_input,
                        placeholder=str(hot_reload_retry_interval),
                        ttl=600,
                        style="primary",
                    ),
                ]
            )
        buttons.extend(
            [
                [
                    self.Button.inline(
                        self.strings(
                            "btn_hot_reload_disable_on_first_fail",
                            state=self.strings(
                                "state_on"
                                if hot_reload_disable_on_first_fail
                                else "state_off"
                            ),
                        ),
                        self.on_toggle_hot_reload_disable_on_first_fail,
                        ttl=600,
                        style=(
                            "success" if hot_reload_disable_on_first_fail else "danger"
                        ),
                    )
                ],
                [
                    self.Button.inline(
                        self.strings(
                            "btn_hot_load_new_patches",
                            state=self.strings(
                                "state_on" if hot_load_new_patches else "state_off"
                            ),
                        ),
                        self.on_toggle_hot_load_new_patches,
                        ttl=600,
                        style="success" if hot_load_new_patches else "danger",
                    )
                ],
                [
                    self.Button.inline(
                        f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                        self.on_experimental_settings_menu,
                        ttl=600,
                    )
                ],
            ]
        )
        return text, buttons

    @callback(ttl=600)
    async def on_experimental_settings_menu(self, call) -> None:
        self._experimental_settings_event = call
        if self._get_pm() is None:
            await call.answer(self.strings("unsupported_current_kernel"), alert=True)
            await call.edit(
                f"{self.C['warning']} <b>{self.strings('experimental_unavailable_title')}</b>\n\n"
                f"<blockquote>{self.strings('experimental_unavailable_desc')}</blockquote>",
                buttons=[
                    [
                        self.Button.inline(
                            f"{self._clear_text(self.C['back'])} {self.strings('btn_back')}",
                            self.on_settings_menu,
                            ttl=600,
                        )
                    ]
                ],
            )
            return
        text, buttons = self._build_experimental_settings_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_hot_reload_settings_menu(self, call) -> None:
        self._hot_reload_settings_event = call
        text, buttons = self._build_hot_reload_settings_page()
        await call.edit(text, buttons=buttons)

    async def _refresh_experimental_settings_event(self) -> bool:
        call = getattr(self, "_experimental_settings_event", None)
        if call is None:
            return False
        try:
            text, buttons = self._build_experimental_settings_page()
            await call.edit(text, buttons=buttons)
            return True
        except Exception as exc:
            self.log.debug("cannot refresh experimental settings menu: %s", exc)
            return False

    async def _refresh_hot_reload_runtime_and_page(
        self, call: Any | None = None
    ) -> None:
        self._set_runtime_hot_reload(
            bool(self._cfg("experimental_patch_hot_reload", False))
        )
        if call is not None:
            self._hot_reload_settings_event = call
        if not await self._refresh_hot_reload_settings_event() and call is not None:
            text, buttons = self._build_hot_reload_settings_page()
            await call.edit(text, buttons=buttons)

    async def _refresh_hot_reload_settings_event(self) -> bool:
        call = getattr(self, "_hot_reload_settings_event", None)
        if call is None:
            return False
        try:
            text, buttons = self._build_hot_reload_settings_page()
            await call.edit(text, buttons=buttons)
            return True
        except Exception as exc:
            self.log.debug("cannot refresh hot reload settings menu: %s", exc)
            return False

    @callback(ttl=600)
    async def on_toggle_stealth(self, call) -> None:
        new_value = not bool(self._cfg("stealth_mode", False))
        if new_value:
            try:
                self.config["stealth_mode"] = True
                self._apply_stealth_from_config()
            except RuntimeError as exc:
                self.config["stealth_mode"] = False
                await self._save_config()
                await call.answer(str(exc), alert=True)
                text, buttons = self._build_settings_page()
                await call.edit(text, buttons=buttons)
                return
            await self._save_config()
            await call.answer(self.strings("stealth_enabled"), alert=False)
        else:
            self.config["stealth_mode"] = False
            self._disable_runtime_stealth()
            await self._save_config()
            await call.answer(self.strings("stealth_disabled"), alert=False)
        text, buttons = self._build_settings_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_toggle_auto_update(self, call) -> None:
        new_value = not bool(self._cfg("auto_update_kernel", False))
        self.config["auto_update_kernel"] = new_value
        await self._save_config()
        self._ensure_update_task()
        await call.answer(
            self.strings(
                "auto_update_enabled" if new_value else "auto_update_disabled"
            ),
            alert=False,
        )
        text, buttons = self._build_settings_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_toggle_notifications(self, call) -> None:
        new_value = not bool(self._cfg("update_notifications", True))
        self.config["update_notifications"] = new_value
        await self._save_config()
        self._ensure_update_task()
        await call.answer(
            self.strings(
                "notifications_enabled" if new_value else "notifications_disabled"
            ),
            alert=False,
        )
        text, buttons = self._build_settings_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_cycle_notification_delay(self, call) -> None:
        delay = self._next_notification_delay_seconds()
        self.config["update_notification_delay"] = delay
        await self._save_config()
        await call.answer(
            self.strings("settings_notify_delay_answer", delay=delay),
            alert=False,
        )
        text, buttons = self._build_notify_settings_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_toggle_manager_update_notifications(self, call) -> None:
        new_value = not bool(self._cfg("manager_update_notifications", True))
        self.config["manager_update_notifications"] = new_value
        await self._save_config()
        self._ensure_update_task()
        await call.answer(
            self.strings(
                "manager_notifications_enabled"
                if new_value
                else "manager_notifications_disabled"
            ),
            alert=False,
        )
        text, buttons = self._build_notify_settings_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_toggle_client_patch(self, call) -> None:
        self._client_patch_event = call
        new_value = not self._is_client_patch_enabled()
        if new_value and not self._set_runtime_client_patch(True):
            await call.answer(self.strings("client_patch_unsupported"), alert=True)
            return
        if not new_value:
            self._clear_runtime_client_patch()
        self._client_patch_enabled_db = new_value
        await self._save_client_patch_db_state()
        await call.answer(
            self.strings(
                "client_patch_enabled" if new_value else "client_patch_disabled"
            ),
            alert=False,
        )
        text, buttons = self._build_client_patch_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_toggle_client_patch_quick(self, call) -> None:
        new_value = not self._is_client_patch_enabled()
        if new_value and not self._set_runtime_client_patch(True):
            await call.answer(self.strings("client_patch_unsupported"), alert=True)
            return
        if not new_value:
            self._clear_runtime_client_patch()
        self._client_patch_enabled_db = new_value
        await self._save_client_patch_db_state()
        await call.answer(
            self.strings(
                "client_patch_enabled" if new_value else "client_patch_disabled"
            ),
            alert=False,
        )
        text, buttons = self._build_experimental_settings_page()
        await call.edit(text, buttons=buttons)

    async def _set_client_patch_input(
        self,
        event: Any,
        text: str,
        config_key: str,
        label: str,
    ) -> None:
        value = str(text or "").strip()
        if value.casefold() in {"-", "none", "null", "clear", "reset", "off"}:
            value = ""
        self.config[config_key] = value
        if self._is_client_patch_enabled() and not self._set_runtime_client_patch(True):
            await self._edit(event, f"🚫 {self.strings('client_patch_unsupported')}")
            return
        await self._save_config()
        await self._save_client_patch_db_state()
        await self._refresh_client_patch_event()
        display = html.escape(value or self.strings("client_patch_value_cleared"))
        await self._edit(
            event,
            f"{self.C['true']} <b>{self.strings('client_patch_updated')}</b>\n"
            f"{html.escape(label)}: <code>{display}</code>\n\n"
            f"<blockquote><em>{self.strings('client_patch_clear_hint')}</em></blockquote>",
        )

    async def on_client_patch_app_version_input(
        self,
        event: Any,
        text: str,
        data: Any = None,
    ) -> None:
        await self._set_client_patch_input(
            event, text, "client_patch_app_version", "app_version"
        )

    async def on_client_patch_device_model_input(
        self,
        event: Any,
        text: str,
        data: Any = None,
    ) -> None:
        await self._set_client_patch_input(
            event, text, "client_patch_device_model", "device_model"
        )

    async def on_client_patch_system_version_input(
        self,
        event: Any,
        text: str,
        data: Any = None,
    ) -> None:
        await self._set_client_patch_input(
            event, text, "client_patch_system_version", "system_version"
        )

    async def on_client_patch_lang_code_input(
        self,
        event: Any,
        text: str,
        data: Any = None,
    ) -> None:
        await self._set_client_patch_input(
            event, text, "client_patch_lang_code", "lang_code"
        )

    async def on_client_patch_system_lang_code_input(
        self,
        event: Any,
        text: str,
        data: Any = None,
    ) -> None:
        await self._set_client_patch_input(
            event,
            text,
            "client_patch_system_lang_code",
            "system_lang_code",
        )

    @callback(ttl=600)
    async def on_clear_client_patch_options(self, call) -> None:
        self._client_patch_event = call
        for key in (
            "client_patch_app_version",
            "client_patch_device_model",
            "client_patch_system_version",
            "client_patch_lang_code",
            "client_patch_system_lang_code",
        ):
            self.config[key] = ""
        if self._is_client_patch_enabled():
            self._set_runtime_client_patch(True)
        await self._save_config()
        await self._save_client_patch_db_state()
        await call.answer(self.strings("client_cleared"), alert=False)
        text, buttons = self._build_client_patch_page()
        await call.edit(text, buttons=buttons)

    async def _toggle_extera_scope(self, call: Any, scope: str) -> None:
        self._extera_proxy_event = call
        scopes = self._extera_scopes_from_config()
        if scope == "root":
            scopes = ["kernel"]
        elif "root" in scopes:
            scopes = ["kernel", "client", "event"]
            scopes = [item for item in scopes if item != scope]
        elif scope in scopes:
            scopes = [item for item in scopes if item != scope]
        else:
            scopes.append(scope)
        self._save_extera_scopes_to_config(scopes)
        scopes = self._extera_scopes_from_config()
        if not self._set_runtime_extera_proxy_scopes(scopes):
            await call.answer(self.strings("extera_unsupported_scopes"), alert=True)
            return
        await self._save_config()
        await call.answer(
            self.strings(
                "extera_scope_answer",
                scope=scope,
                state=self.strings("state_on" if scope in scopes else "state_off"),
            ),
            alert=False,
        )
        text, buttons = self._build_extera_proxy_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_toggle_extera_scope_root(self, call) -> None:
        await self._toggle_extera_scope(call, "root")

    @callback(ttl=600)
    async def on_toggle_extera_scope_kernel(self, call) -> None:
        await self._toggle_extera_scope(call, "kernel")

    @callback(ttl=600)
    async def on_toggle_extera_scope_client(self, call) -> None:
        await self._toggle_extera_scope(call, "client")

    @callback(ttl=600)
    async def on_toggle_extera_scope_event(self, call) -> None:
        await self._toggle_extera_scope(call, "event")

    @callback(ttl=600)
    async def on_toggle_extera_proxy_all(self, call) -> None:
        self._extera_proxy_event = call
        new_value = not bool(self._cfg("extera_proxy_all", False))
        if new_value and not self._set_runtime_extera_proxy_all(True):
            await call.answer(self.strings("extera_unsupported"), alert=True)
            return
        if not new_value:
            self._set_runtime_extera_proxy_all(False)
        self.config["extera_proxy_all"] = new_value
        await self._save_config()
        await call.answer(
            self.strings(
                "extera_all_on_answer" if new_value else "extera_all_off_answer"
            ),
            alert=new_value,
        )
        text, buttons = self._build_extera_proxy_page()
        await call.edit(text, buttons=buttons)

    async def on_extera_proxy_add_input(
        self,
        event: Any,
        text: str,
        data: Any = None,
    ) -> None:
        module_name = str(text or "").strip()
        if not module_name:
            await self._edit(event, f"🚫 {self.strings('extera_name_required')}")
            return
        modules = self._extera_modules_from_config()
        if module_name.casefold() not in {item.casefold() for item in modules}:
            modules.append(module_name)
        self._save_extera_modules_to_config(modules)
        if not self._set_runtime_extera_proxy_modules(modules):
            await self._edit(event, f"🚫 {self.strings('extera_unsupported')}")
            return
        await self._save_config()
        await self._refresh_extera_proxy_event()
        await self._edit(
            event,
            f"{self.C['warning']} <b>{self.strings('extera_updated')}</b>\n"
            f"{self.strings('extera_add_result', module=html.escape(module_name))}\n\n"
            f"<blockquote><em>{self.strings('extera_trusted_warning')}</em></blockquote>",
        )

    async def on_extera_proxy_remove_input(
        self,
        event: Any,
        text: str,
        data: Any = None,
    ) -> None:
        module_name = str(text or "").strip()
        modules = [
            item
            for item in self._extera_modules_from_config()
            if item.casefold() != module_name.casefold()
        ]
        self._save_extera_modules_to_config(modules)
        self._set_runtime_extera_proxy_modules(modules)
        await self._save_config()
        await self._refresh_extera_proxy_event()
        await self._edit(
            event,
            f"{self.C['true']} {self.strings('extera_remove_result', module=html.escape(module_name or 'unknown'))}",
        )

    @callback(ttl=600)
    async def on_clear_extera_proxy_modules(self, call) -> None:
        self._extera_proxy_event = call
        self._save_extera_modules_to_config([])
        self._set_runtime_extera_proxy_modules([])
        await self._save_config()
        await call.answer(self.strings("extera_clear_answer"), alert=False)
        text, buttons = self._build_extera_proxy_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_clear_extera_proxy_modules_quick(self, call) -> None:
        self._save_extera_modules_to_config([])
        self._set_runtime_extera_proxy_modules([])
        await self._save_config()
        await call.answer(self.strings("extera_clear_answer"), alert=False)
        await self._refresh_extera_proxy_event()
        text, buttons = self._build_experimental_settings_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_toggle_patch_events(self, call) -> None:
        new_value = not bool(self._cfg("experimental_patch_events", False))
        if new_value and not self._set_runtime_patch_events(True):
            await call.answer(self.strings("unsupported_current_kernel"), alert=True)
            return
        if not new_value:
            self._set_runtime_patch_events(False)
        self.config["experimental_patch_events"] = new_value
        await self._save_config()
        await call.answer(
            self.strings(
                "patch_events_enabled" if new_value else "patch_events_disabled"
            ),
            alert=False,
        )
        text, buttons = self._build_experimental_settings_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_toggle_patch_hot_reload(self, call) -> None:
        new_value = not bool(self._cfg("experimental_patch_hot_reload", False))
        if new_value and not self._set_runtime_hot_reload(True):
            await call.answer(self.strings("unsupported_current_kernel"), alert=True)
            return
        if not new_value:
            self._set_runtime_hot_reload(False)
        self.config["experimental_patch_hot_reload"] = new_value
        await self._save_config()
        await call.answer(
            self.strings("hot_reload_enabled" if new_value else "hot_reload_disabled"),
            alert=False,
        )
        text, buttons = self._build_experimental_settings_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_toggle_hot_reload_smart_disable(self, call) -> None:
        self.config["experimental_hot_reload_smart_disable"] = not bool(
            self._cfg("experimental_hot_reload_smart_disable", False)
        )
        await self._save_config()
        await call.answer("OK", alert=False)
        await self._refresh_hot_reload_runtime_and_page(call)

    async def on_hot_reload_retry_interval_input(
        self,
        event: Any,
        text: str,
        data: Any = None,
    ) -> None:
        try:
            value = int(str(text or "").strip())
        except (TypeError, ValueError):
            value = 0
        if value < 1 or value > 3600:
            await self._refresh_experimental_settings_event()
            with contextlib.suppress(Exception):
                await self._edit(
                    event, f"🚫 {self.strings('hot_reload_retry_interval_invalid')}"
                )
            return
        self.config["experimental_hot_reload_retry_interval"] = value
        await self._save_config()
        await self._refresh_hot_reload_runtime_and_page(None)
        with contextlib.suppress(Exception):
            await self._edit(
                event,
                f"{self.C['true']} {self.strings('hot_reload_retry_interval_answer', interval=value)}",
            )

    @callback(ttl=600)
    async def on_toggle_hot_reload_disable_on_first_fail(self, call) -> None:
        self.config["experimental_hot_reload_disable_on_first_fail"] = not bool(
            self._cfg("experimental_hot_reload_disable_on_first_fail", False)
        )
        await self._save_config()
        await call.answer("OK", alert=False)
        await self._refresh_hot_reload_runtime_and_page(call)

    @callback(ttl=600)
    async def on_toggle_hot_load_new_patches(self, call) -> None:
        self.config["experimental_hot_load_new_patches"] = not bool(
            self._cfg("experimental_hot_load_new_patches", False)
        )
        await self._save_config()
        await call.answer("OK", alert=False)
        await self._refresh_hot_reload_runtime_and_page(call)

    def _patch_button_entries(self, pm: Any) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        def add(patch_key: str, target: str, status: str) -> None:
            target_text = str(target)
            entry_key = (patch_key, self._patch_target_norm(pm, target_text))
            if entry_key in seen:
                return
            seen.add(entry_key)
            entries.append(
                {"patch_key": patch_key, "target": target_text, "status": status}
            )

        for patch_key, target_norm in pm.applied_patches:
            info = pm.applied_patches[(patch_key, target_norm)]
            add(patch_key, str(info.get("target", target_norm)), "applied")
        for patch_key, target in pm.failed_patches:
            add(patch_key, str(target), "failed")
        for patch_key, targets in pm.pending_patches.items():
            for target in targets:
                add(patch_key, str(target), "pending")
        for patch_key in sorted(getattr(pm, "disabled_patches", set()) or set()):
            mod = pm.loaded_patches.get(patch_key)
            if mod is None:
                add(str(patch_key), "<disabled>", "disabled")
                continue
            targets = pm._patch_targets(mod) if hasattr(pm, "_patch_targets") else []
            for target in targets or ["<disabled>"]:
                add(str(patch_key), str(target), "disabled")
        return entries

    def _patch_target_norm(self, pm: Any, target: str) -> str:
        normalize = getattr(pm, "_normalize", None)
        return (
            normalize(target) if callable(normalize) else str(target).strip().casefold()
        )

    def _patch_display_name_safe(self, pm: Any, patch_key: str) -> str:
        mod = pm.loaded_patches.get(patch_key)
        try:
            return pm._patch_display_name(mod, patch_key) if mod else patch_key
        except Exception:
            return patch_key

    def _patch_detail_info(self, pm: Any, data: Any) -> dict[str, Any]:
        data = data or {}
        patch_key = str(data.get("patch_key", ""))
        target = str(data.get("target", ""))
        target_norm = self._patch_target_norm(pm, target)
        applied_key = (patch_key, target_norm)
        mod = pm.loaded_patches.get(patch_key)
        name = self._patch_display_name_safe(pm, patch_key)
        file_path = getattr(mod, "__xpatch_file__", "") if mod else ""
        info: dict[str, Any] = {
            "patch_key": patch_key,
            "name": name,
            "target": target,
            "target_norm": target_norm,
            "file": file_path or "unknown",
            "status": "loaded" if mod else "unknown",
            "result": "",
            "error": "",
            "pending_reason": "",
            "traceback": "",
            "has_unapply": False,
            "disabled": False,
            "required_xkernel": "",
            "current_xkernel": "",
            "version_ok": True,
            "version_known": False,
        }

        is_disabled = getattr(pm, "is_patch_disabled", lambda key: False)
        info["disabled"] = (
            bool(is_disabled(patch_key)) if callable(is_disabled) else False
        )
        if info["disabled"]:
            info["status"] = "disabled"

        if mod is not None:
            unapply_callback = getattr(pm, "_unapply_callback", None)
            if callable(unapply_callback):
                info["has_unapply"] = bool(unapply_callback(mod))
            required_getter = getattr(pm, "_patch_required_xkernel", None)
            current_getter = getattr(pm, "_current_xkernel_version", None)
            version_less = getattr(pm, "_version_less", None)
            format_version = getattr(pm, "_format_version", None)
            required = required_getter(mod) if callable(required_getter) else None
            current = current_getter() if callable(current_getter) else None
            if required and current:
                info["version_known"] = True
                info["version_ok"] = (
                    not bool(version_less(current, required))
                    if callable(version_less)
                    else True
                )
                if callable(format_version):
                    info["required_xkernel"] = format_version(required)
                    info["current_xkernel"] = format_version(current)
                else:
                    info["required_xkernel"] = ".".join(str(part) for part in required)
                    info["current_xkernel"] = ".".join(str(part) for part in current)

        if applied_key in pm.applied_patches:
            applied = pm.applied_patches[applied_key]
            if not info["disabled"]:
                info["status"] = "applied"
            info["target"] = str(applied.get("target", target))
            info["result"] = repr(applied.get("result", ""))
            return info

        for (failed_key, failed_target), error in pm.failed_patches.items():
            if failed_key != patch_key:
                continue
            if (
                str(failed_target) == target
                or self._patch_target_norm(pm, str(failed_target)) == target_norm
            ):
                info["status"] = "failed"
                info["target"] = str(failed_target)
                info["error"] = str(error)
                tracebacks = getattr(pm, "failed_tracebacks", {}) or {}
                info["traceback"] = str(tracebacks.get((patch_key, failed_target), ""))
                return info

        pending = pm.pending_patches.get(patch_key, [])
        for pending_target in pending:
            if self._patch_target_norm(pm, str(pending_target)) == target_norm:
                info["status"] = "pending"
                info["target"] = str(pending_target)
                reasons = getattr(pm, "pending_reasons", {}) or {}
                info["pending_reason"] = str(reasons.get((patch_key, target_norm), ""))
                return info
        return info

    def _patch_status_icon(self, status: str) -> str:
        if status == "applied":
            return self.C["true"]
        if status == "failed":
            return self.C["off"]
        if status == "pending":
            return self.C["pending"]
        if status == "disabled":
            return self.C["warning"]
        return self.C["info"]

    def _patch_detail_text(self, info: dict[str, Any]) -> str:
        error = str(info.get("error") or "")
        full_traceback = str(info.get("traceback") or "")
        result = str(info.get("result") or "")
        pending_reason = str(info.get("pending_reason") or "")
        version_known = bool(info.get("version_known", False))
        version_ok = bool(info.get("version_ok", True))
        required_xkernel = str(info.get("required_xkernel") or "")
        lines = [
            f"{self.C['menu']} <b>{self.strings('patch_detail_title')}</b>",
            "",
            f"{self._patch_status_icon(str(info['status']))} {self.strings('patch_status_label')} <b>{html.escape(str(info['status']))}</b>",
            f"<blockquote expandable>{self.strings('patch_label')} <code>{html.escape(str(info['name']))}</code>",
            f"{self.strings('patch_target_label')} <code>{html.escape(str(info['target']))}</code>",
            f"{self.strings('patch_file_label')} <code>{html.escape(str(info['file']))}</code>",
            f"{self.strings('patch_key_label')} <code>{html.escape(str(info['patch_key']))}</code></blockquote>",
        ]
        if result:
            lines += [
                "",
                f"<blockquote expandable>{self.C['result']} <b>{self.strings('patch_result_label')}</b>\n<code>{html.escape(result)}</code></blockquote>",
            ]
        if pending_reason:
            lines += [
                "",
                f"<blockquote expandable>{self.C['pending']} <b>{self.strings('patch_pending_reason_label')}</b>\n<code>{html.escape(pending_reason)}</code></blockquote>",
            ]
        if error:
            lines += [
                "",
                f"<blockquote expandable>{self.C['off']} <b>{self.strings('patch_error_label')}</b>\n{html.escape(error)}</blockquote>",
            ]
        if full_traceback:
            lines += [
                "",
                f"<blockquote expandable>{self.C['logs']} <b>{self.strings('patch_traceback_label')}</b>\n<code>{html.escape(full_traceback)}</code></blockquote>",
            ]
        if version_known and not version_ok:
            lines += [
                "",
                f"<blockquote>{self.C['warning']} <b>{self.strings('patch_min_version', version=html.escape(required_xkernel))}</b></blockquote>",
            ]
        elif version_known:
            lines += [
                "",
                f"<blockquote>{self.C['on']} <b>{self.strings('patch_version_ok')}</b></blockquote>",
            ]
        else:
            lines += [
                "",
                f"<blockquote>{self.C['warning']} <b>{self.strings('patch_min_version_unknown')}</b></blockquote>",
            ]
        return "\n".join(lines)

    @callback(ttl=600)
    async def on_patches_menu(self, call) -> None:
        C = self.C
        pm = self._get_pm()
        if pm is None:
            await call.answer(self.strings("xpatch_inactive_alert"), alert=True)
            return

        applied = len(pm.applied_patches)
        pending = sum(len(v) for v in pm.pending_patches.values())
        failed = len(pm.failed_patches)
        disabled = len(getattr(pm, "disabled_patches", set()) or set())
        text = (
            f"{C['menu']} <b>{self.strings('patches_title')}</b>\n\n"
            f"{C['true']} {self.strings('patches_stats', applied=applied, pending=pending, failed=failed, disabled=disabled)}\n"
            f"<blockquote>{self.strings('patches_hint')}</blockquote>"
        )

        buttons: list[list] = []
        for entry in self._patch_button_entries(pm):
            info = self._patch_detail_info(pm, entry)
            label = (
                f"{self._clear_text(self._patch_status_icon(str(info['status'])))} "
                f"{str(info['name'])[:32]} > {str(info['target'])[:24]}"
            )
            buttons.append(
                [self.Button.inline(label, self.on_patch_detail, data=entry, ttl=600)]
            )

        if not buttons:
            text += f"\n\n<i>{self.strings('patches_empty')}</i>"
        buttons.append(
            [
                self.Button.inline(
                    f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                    self.on_back_to_main,
                    ttl=600,
                )
            ]
        )
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_patch_detail(self, call, data: Any = None) -> None:
        pm = self._get_pm()
        if pm is None:
            await call.answer(self.strings("xpatch_inactive_alert"), alert=True)
            return
        info = self._patch_detail_info(pm, data)
        reload_label = self.strings("btn_reload_patch")
        if info.get("status") == "failed" and str(info.get("target")) == "<load>":
            reload_label = self.strings("btn_load_problem_patch")
        buttons: list[list] = []
        buttons.append(
            [
                self.Button.inline(
                    f"🔁 {reload_label}",
                    self.on_patch_reload,
                    data=data,
                    ttl=600,
                )
            ]
        )
        if info["disabled"]:
            buttons.append(
                [
                    self.Button.inline(
                        f"✅ {self.strings('btn_enable_patch')}",
                        self.on_patch_enable,
                        data=data,
                        ttl=600,
                    )
                ]
            )
        else:
            buttons.append(
                [
                    self.Button.inline(
                        f"🚫 {self.strings('btn_disable_patch')}",
                        self.on_patch_disable,
                        data=data,
                        ttl=600,
                    )
                ]
            )
        if info["status"] == "applied" and info.get("has_unapply"):
            buttons.append(
                [
                    self.Button.inline(
                        f"↩️ {self.strings('btn_unapply_patch')}",
                        self.on_patch_unapply,
                        data=data,
                        ttl=600,
                    )
                ]
            )
        if info["status"] == "failed" and str(info["target"]) not in {
            "<load>",
            "<missing-target>",
        }:
            buttons.append(
                [
                    self.Button.inline(
                        f"🔁 {self.strings('btn_retry_patch')}",
                        self.on_patch_retry,
                        data=data,
                        ttl=600,
                    )
                ]
            )
        buttons.append(
            [
                self.Button.inline(
                    f"{self._clear_text(self.C['back'])} {self.strings('btn_back')}",
                    self.on_patches_menu,
                    ttl=600,
                )
            ]
        )
        await call.edit(self._patch_detail_text(info), buttons=buttons)

    @callback(ttl=600)
    async def on_patch_reload(self, call, data: Any = None) -> None:
        pm = self._get_pm()
        if pm is None:
            await call.answer(self.strings("xpatch_inactive_alert"), alert=True)
            return
        patch_key = str((data or {}).get("patch_key", ""))
        reload_patch_key = getattr(pm, "reload_patch_key", None)
        if not callable(reload_patch_key):
            await call.answer(self.strings("patch_reload_unsupported"), alert=True)
            return
        result = await reload_patch_key(patch_key)
        if result.get("failed"):
            await call.answer(self.strings("patch_reload_failed"), alert=True)
        elif result.get("missing"):
            await call.answer(self.strings("patch_file_not_found"), alert=True)
        else:
            await call.answer(self.strings("patch_reloaded"), alert=False)
        await self.on_patch_detail(call, data)

    @callback(ttl=600)
    async def on_patch_unapply(self, call, data: Any = None) -> None:
        pm = self._get_pm()
        if pm is None:
            await call.answer(self.strings("xpatch_inactive_alert"), alert=True)
            return
        patch_key = str((data or {}).get("patch_key", ""))
        target = str((data or {}).get("target", ""))
        result = await pm.unapply_patch(patch_key, target)
        await call.answer(
            self.strings("patch_unapply_result", result=result),
            alert=result == "failed",
        )
        await self.on_patch_detail(call, data)

    async def _set_patch_disabled_from_detail(
        self, call, data: Any, disabled: bool
    ) -> None:
        pm = self._get_pm()
        if pm is None:
            await call.answer(self.strings("xpatch_inactive_alert"), alert=True)
            return
        patch_key = str((data or {}).get("patch_key", ""))
        setter = getattr(pm, "set_patch_disabled", None)
        if not callable(setter):
            await call.answer(self.strings("patch_toggle_unsupported"), alert=True)
            return
        setter(patch_key, disabled)
        if disabled:
            await pm.unapply_patch_key(patch_key)
            await call.answer(self.strings("patch_disabled_answer"), alert=False)
        else:
            await pm.apply_all(force=True)
            await call.answer(self.strings("patch_enabled_answer"), alert=False)
        await self.on_patch_detail(call, data)

    @callback(ttl=600)
    async def on_patch_disable(self, call, data: Any = None) -> None:
        await self._set_patch_disabled_from_detail(call, data, True)

    @callback(ttl=600)
    async def on_patch_enable(self, call, data: Any = None) -> None:
        await self._set_patch_disabled_from_detail(call, data, False)

    @callback(ttl=600)
    async def on_patch_retry(self, call, data: Any = None) -> None:
        pm = self._get_pm()
        if pm is None:
            await call.answer(self.strings("xpatch_inactive_alert"), alert=True)
            return
        info = self._patch_detail_info(pm, data)
        target = str(info.get("target") or "")
        await call.answer(self.strings("patch_retry_answer"), alert=False)
        try:
            if target in {"<load>", "<missing-target>", ""}:
                await pm.apply_all()
            else:
                await pm.apply_for_target(target, force=True)
        except Exception as exc:
            self.log.exception("XPatch retry failed")
            await call.answer(str(exc), alert=True)
        await self.on_patch_detail(call, data)

    @callback(ttl=600)
    async def on_details_menu(self, call) -> None:
        C = self.C
        pm = self._get_pm()

        target_path = self._xkernel_path()
        default_core = self._get_default_core()
        backups = self._backup_files()

        lines: list[str] = []

        if target_path.exists():
            size_kb = target_path.stat().st_size / 1024
            content = target_path.read_text(encoding="utf-8")
            sha = self._sha256(content)
            lines += [
                f"{C['file']} {self.strings('details_file_label')} <code>{html.escape(str(target_path))}</code>",
                f"{C['lock']} SHA256: <code>{sha[:16]}…</code>",
                f"{C['dir']} {self.strings('details_size_label')} <code>{size_kb:.1f} KB</code>",
                f"{C['diskette']} {self.strings('details_backups_label')} <code>{len(backups)}</code>",
                "",
            ]
        else:
            lines += [
                f"{C['warning']} {self.strings('details_not_found')}",
                f"<code>{html.escape(str(target_path))}</code>",
                "",
            ]

        ver = html.escape(str(self._kernel_attr("VERSION", "?")))
        xkernel_ver = html.escape(self._display_xkernel_version())
        core_name = html.escape(str(self._kernel_attr("CORE_NAME", "?")))
        patches_dir = html.escape(
            str(getattr(pm, "patches_dir", "patches") if pm else "patches")
        )

        lines += [
            f"{C['settings']} Core: <code>{core_name}</code>",
            f"{C['menu']} Version: <code>{ver}</code>",
            f"{C['info']} Version XPatchKernel: <code>{xkernel_ver}</code>",
            f"{C['file']} Patches dir: <code>{patches_dir}</code>",
            f"{C['lock']} {self.strings('details_default_core')} <code>{html.escape(default_core or self.strings('details_not_set'))}</code>",
            f"{C['pc']} Platform: <code>{html.escape(get_platform_name())}</code>",
        ]

        text = (
            f"{C['info']} <b>{self.strings('details_title')}</b>\n\n<blockquote>"
            + "\n".join(lines)
            + "</blockquote>"
        )
        buttons = [
            [
                self.Button.inline(
                    f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                    self.on_back_to_main,
                    ttl=600,
                ),
                self.Button.inline("⏪ Rollback", self.on_rollback_confirm, ttl=300),
            ],
        ]
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_install_start(self, call) -> None:
        C = self.C
        await call.edit(
            f"{C['install']} <b>{self.strings('install_loading')}</b>\n"
            f"{C['moon']} {self.strings('platform_label')} <code>{html.escape(get_platform_name())}</code>",
        )
        try:
            source = await self._download_xkernel()
            self._validate_xkernel_source(source)

            target_path = self._xkernel_path()
            self._backup_existing(target_path)
            self._write_atomic(target_path, source)
            sha = self._sha256(source)

            text = (
                f"{C['true']} <b>{self.strings('install_done_title')}</b>\n\n"
                f"<blockquote>"
                f"{C['file']} {self.strings('details_file_label')} <code>{html.escape(str(target_path))}</code>\n"
                f"{C['lock']} SHA: <code>{sha[:16]}…</code>"
                f"</blockquote>\n"
                f"{C['warning']} <b>{self.strings('install_default_prompt')}</b>\n"
                f"<blockquote>{self.strings('install_default_desc')}</blockquote>"
            )
            buttons = [
                [
                    self.Button.inline(
                        f"✅ {self.strings('btn_set_default')}",
                        self.on_install_set_default,
                        ttl=300,
                    ),
                    self.Button.inline(
                        self.strings("btn_no_thanks"),
                        self.on_install_skip_default,
                        ttl=300,
                    ),
                ],
            ]
        except Exception as exc:
            self.log.exception("XKernel inline install failed")
            text = (
                f"🚫 <b>{self.strings('install_error_title')}</b>\n"
                f"<pre>{html.escape(str(exc))}</pre>"
            )
            buttons = [
                [
                    self.Button.inline(
                        f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                        self.on_back_to_main,
                        ttl=600,
                    )
                ],
            ]
        await call.edit(text, buttons=buttons)

    def _install_finish_page(self, default_changed: bool) -> tuple[str, list]:
        C = self.C
        default_text = (
            "XKernel" if default_changed else self.strings("install_default_unchanged")
        )
        text = (
            f"{C['true']} <b>{self.strings('install_finish_title')}</b>\n\n"
            f"<blockquote>{C['lock']} Default core: <code>{html.escape(default_text)}</code></blockquote>\n"
            f"{C['warning']} <i>{self.strings('restart_required')}</i>"
        )
        buttons = [
            [
                self.Button.inline(
                    f"{self._clear_text(C['reboot'])} {self.strings('btn_restart')}",
                    self.on_restart,
                    ttl=120,
                ),
                self.Button.inline(
                    f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                    self.on_back_to_main,
                    ttl=600,
                ),
            ],
        ]
        return text, buttons

    @callback(ttl=300)
    async def on_install_set_default(self, call) -> None:
        self._set_default_core("XKernel")
        await call.answer(self.strings("install_default_set_answer"), alert=False)
        text, buttons = self._install_finish_page(default_changed=True)
        await call.edit(text, buttons=buttons)

    @callback(ttl=300)
    async def on_install_skip_default(self, call) -> None:
        await call.answer(self.strings("install_default_skip_answer"), alert=False)
        text, buttons = self._install_finish_page(default_changed=False)
        await call.edit(text, buttons=buttons)

    @callback(ttl=300)
    async def on_check_update(self, call) -> None:
        await call.answer(self.strings("update_checking"), alert=False)
        try:
            update = await self._get_kernel_update_info()
        except Exception as exc:
            self.log.exception("XKernel update check failed")
            await call.edit(
                f"🚫 <b>{self.strings('update_check_failed_title')}</b>\n<pre>{html.escape(str(exc))}</pre>",
                buttons=[
                    [
                        self.Button.inline(
                            f"{self._clear_text(self.C['back'])} {self.strings('btn_back')}",
                            self.on_back_to_main,
                            ttl=600,
                        )
                    ]
                ],
            )
            return

        if not update["available"]:
            await call.edit(
                f"{self.C['true']} <b>{self.strings('update_current_title')}</b>\n\n"
                f"<blockquote>"
                f"{self.strings('local_label')} <code>{self._format_version(update['local_version'])}</code>\n"
                f"{self.strings('remote_label')} <code>{self._format_version(update['remote_version'])}</code>"
                f"</blockquote>",
                buttons=[
                    [
                        self.Button.inline(
                            f"{self._clear_text(self.C['back'])} {self.strings('btn_back')}",
                            self.on_back_to_main,
                            ttl=600,
                        )
                    ]
                ],
            )
            return

        await call.edit(
            f"{self.C['reload']} <b>{self.strings('update_available_title')}</b>\n\n"
            f"<blockquote>"
            f"{self.strings('local_label')} <code>{self._format_version(update['local_version'])}</code>\n"
            f"{self.strings('remote_label')} <code>{self._format_version(update['remote_version'])}</code>"
            f"</blockquote>",
            buttons=[
                [
                    self.Button.inline(
                        f"⬆️ {self.strings('btn_update_now')}",
                        self.on_update_now,
                        ttl=300,
                    ),
                    self.Button.inline(
                        f"{self._clear_text(self.C['back'])} {self.strings('btn_back')}",
                        self.on_back_to_main,
                        ttl=600,
                    ),
                ]
            ],
        )

    @callback(ttl=300)
    async def on_update_now(self, call) -> None:
        C = self.C
        await call.edit(f"{C['loading']} <b>{self.strings('update_loading')}</b>")
        try:
            target_path, sha, remote_version = await self._install_latest_xkernel()
            await self._remember_notified_version(remote_version)
        except Exception as exc:
            self.log.exception("XKernel update install failed")
            await call.edit(
                f"🚫 <b>{self.strings('update_failed_title')}</b>\n"
                f"<pre>{html.escape(str(exc))}</pre>\n\n"
                f"{self.strings('reopen_manager_hint')} <code>.xm</code>",
            )
            return

        await call.edit(
            f"{C['true']} <b>{self.strings('update_done_title')}</b>\n\n"
            f"<blockquote>"
            f"{self.strings('version_label')} <code>{self._format_version(remote_version)}</code>\n"
            f"{C['file']} {self.strings('details_file_label')} <code>{html.escape(str(target_path))}</code>\n"
            f"{C['lock']} SHA: <code>{sha[:16]}…</code>"
            f"</blockquote>\n"
            f"{C['warning']} <i>{self.strings('restart_required')}</i>\n"
            f"<em>{self.strings('reopen_manager_hint')}</em> <code>.xm</code>",
        )

    @callback(ttl=600)
    async def on_apply_all(self, call) -> None:
        C = self.C
        pm = self._get_pm()
        if pm is None:
            await call.answer(self.strings("xpatch_inactive_alert"), alert=True)
            return

        await call.edit(
            f"{C['loading']} <b>{self.strings('apply_all_loading')}</b>",
        )
        try:
            result = await pm.apply_all()
        except Exception as exc:
            self.log.exception("apply_patches failed")
            await call.edit(
                f"🚫 <b>{self.strings('apply_all_error_title')}</b>\n<pre>{html.escape(str(exc))}</pre>",
                buttons=[
                    [
                        self.Button.inline(
                            f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                            self.on_back_to_main,
                            ttl=600,
                        )
                    ]
                ],
            )
            return

        applied = result.get("applied", [])
        pending = result.get("pending", [])
        failed = result.get("failed", [])
        skipped = result.get("skipped", [])

        lines: list[str] = [
            f"{C['settings']} <b>{self.strings('apply_all_result_title')}</b>\n"
        ]
        if applied:
            lines.append(
                f"{C['true']} {self.strings('apply_applied_label')} ({len(applied)}):"
            )
            for name, tgt in applied:
                lines.append(
                    f"  <code>{html.escape(name)}</code> > <i>{html.escape(tgt)}</i>"
                )
        if pending:
            lines.append(
                f"\n{C['pending']} {self.strings('apply_pending_label')} ({len(pending)}):"
            )
            for name, tgt in pending:
                lines.append(
                    f"  <code>{html.escape(name)}</code> > <i>{html.escape(tgt)}</i>"
                )
        if failed:
            lines.append(
                f"\n{C['off']} {self.strings('apply_failed_label')} ({len(failed)}):"
            )
            for name, tgt in failed:
                lines.append(
                    f"  <code>{html.escape(name)}</code> > <i>{html.escape(tgt)}</i>"
                )
        if skipped:
            lines.append(f"\n⏭ {self.strings('apply_skipped_label')}: {len(skipped)}")

        needs_restart = bool(applied)
        if needs_restart:
            lines.append(
                f"\n{C['warning']} <i>{self.strings('apply_restart_required')}</i>"
            )

        text = "<blockquote expandable>" + "\n".join(lines) + "</blockquote>"
        back_btn = self.Button.inline(
            f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
            self.on_back_to_main,
            ttl=600,
        )
        buttons = (
            [
                [
                    self.Button.inline(
                        f"{self._clear_text(C['reboot'])} {self.strings('btn_restart')}",
                        self.on_restart,
                        ttl=120,
                    ),
                    back_btn,
                ]
            ]
            if needs_restart
            else [[back_btn]]
        )
        await call.edit(text, buttons=buttons)

    @callback(ttl=300)
    async def on_rollback_confirm(self, call) -> None:
        C = self.C
        backups = self._backup_files()
        if not backups:
            await call.answer(self.strings("rollback_no_backup"), alert=True)
            return

        latest = backups[-1]
        text = (
            f"⏪ <b>{self.strings('rollback_confirm_title')}</b>\n\n"
            f"{self.strings('rollback_will_restore')}\n"
            f"<blockquote><code>{html.escape(str(latest))}</code></blockquote>\n"
            f"{C['warning']} <i>{self.strings('rollback_restart_required')}</i>"
        )
        buttons = [
            [
                self.Button.inline(
                    f"{self._clear_text(self.C['true'])} {self.strings('btn_rollback')}",
                    self.on_rollback_do,
                    ttl=120,
                ),
                self.Button.inline(
                    f"{self._clear_text(C['back'])} {self.strings('btn_cancel')}",
                    self.on_details_menu,
                    ttl=300,
                ),
            ],
        ]
        await call.edit(text, buttons=buttons)

    @callback(ttl=120)
    async def on_rollback_do(self, call) -> None:
        C = self.C
        backups = self._backup_files()
        if not backups:
            await call.answer(self.strings("rollback_no_backup"), alert=True)
            return

        latest_backup = backups[-1]
        target_path = self._xkernel_path()
        try:
            source = latest_backup.read_text(encoding="utf-8")
            self._validate_xkernel_source(source)
            compile(source, str(latest_backup), "exec")
            self._backup_existing(target_path)
            self._write_atomic(target_path, source)
        except Exception as exc:
            self.log.exception("Rollback do failed")
            await call.edit(
                f"🚫 <b>{self.strings('rollback_failed_title')}</b>\n<pre>{html.escape(str(exc))}</pre>",
                buttons=[
                    [
                        self.Button.inline(
                            f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                            self.on_back_to_main,
                            ttl=600,
                        )
                    ]
                ],
            )
            return

        text = (
            f"{C['true']} <b>{self.strings('rollback_done_title')}</b>\n\n"
            f"<blockquote>{self.strings('rollback_restored_label')} <code>{html.escape(str(latest_backup))}</code></blockquote>\n"
            f"{C['warning']} <i>{self.strings('restart_required')}</i>"
        )
        buttons = [
            [
                self.Button.inline(
                    f"{self._clear_text(C['reboot'])} {self.strings('btn_restart')}",
                    self.on_restart,
                    ttl=120,
                ),
                self.Button.inline(
                    f"{self._clear_text(C['back'])} {self.strings('btn_back')}",
                    self.on_back_to_main,
                    ttl=600,
                ),
            ],
        ]
        await call.edit(text, buttons=buttons)

    @callback(ttl=120)
    async def on_restart(self, call) -> None:
        await call.answer(self.strings("restart_answer"), alert=False)
        await self.invoke("restart", chat_id="me")

    @command(
        "xkinstall",
        alias="xki",
        doc_ru="Установить/обновить XKernel (CLI)",
        doc_en="Install/update XKernel (CLI)",
    )
    async def cmd_xkernelinstall(self, event: Any) -> None:
        C = self.C
        text = getattr(event, "text", "") or ""
        set_default = "--default" in text.split()

        await self._edit(
            event,
            f"{C['install']} <b>{self.strings('cli_install_start')}</b>\n"
            f"{C['moon']} {self.strings('platform_label')} <code>{html.escape(get_platform_name())}</code>",
        )
        await asyncio.sleep(1)

        try:
            source = await self._download_xkernel()
            self._validate_xkernel_source(source)

            target_path = self._xkernel_path()
            self._backup_existing(target_path)
            self._write_atomic(target_path, source)
            sha = self._sha256(source)

            default_changed = False
            if set_default:
                self._set_default_core("XKernel")
                default_changed = True

            await self._edit(
                event,
                f"{C['true']} <b>{self.strings('cli_install_done_title')}</b>\n\n"
                f"<blockquote>"
                f"{C['file']} {self.strings('details_file_label')} <code>{html.escape(str(target_path))}</code>\n"
                f"{C['lock']} SHA: <code>{sha[:16]}…</code>\n"
                f"{C['diskette']} Default core: "
                f"<code>{'XKernel' if default_changed else self.strings('install_default_unchanged')}</code>"
                f"</blockquote>\n"
                f"{C['warning']} <i>{self.strings('restart_required')}</i>",
            )
            await self._show_restart_prompt(event)

        except Exception as exc:
            self.log.exception("XKernel install failed")
            await self._edit(
                event,
                f"🚫 <b>{self.strings('cli_install_failed_title')}</b>\n<pre>{html.escape(str(exc))}</pre>",
            )

    @command(
        "xkernelrollback",
        alias="xkr",
        doc_ru="Откатить XKernel на последний backup",
        doc_en="Rollback XKernel to latest backup",
    )
    async def cmd_xkernelrollback(self, event: Any) -> None:
        C = self.C
        backups = self._backup_files()
        if not backups:
            await self._edit(
                event, f"{C['warning']} <b>{self.strings('cli_rollback_not_found')}</b>"
            )
            return

        latest_backup = backups[-1]
        target_path = self._xkernel_path()
        try:
            source = latest_backup.read_text(encoding="utf-8")
            self._validate_xkernel_source(source)
            compile(source, str(latest_backup), "exec")
            self._backup_existing(target_path)
            self._write_atomic(target_path, source)
        except Exception as exc:
            self.log.exception("XKernel rollback failed")
            await self._edit(
                event,
                f"🚫 <b>{self.strings('rollback_failed_title')}</b>\n<code>{html.escape(str(exc))}</code>",
            )
            return

        await self._edit(
            event,
            f"{C['true']} <b>{self.strings('cli_rollback_done_title')}</b>\n\n"
            f"<blockquote>{self.strings('rollback_restored_label')} <code>{html.escape(str(latest_backup))}</code></blockquote>\n"
            f"{C['warning']} <i>{self.strings('restart_required')}</i>",
        )
        await self._show_restart_prompt(event)

    async def _show_restart_prompt(self, event: Any) -> None:
        C = self.C
        await self.inline(
            event.chat_id,
            self.strings("restart_prompt"),
            buttons=[
                [
                    self.Button.inline(
                        f"{self._clear_text(C['reboot'])} {self.strings('btn_reboot')}",
                        self.on_restart,
                        ttl=120,
                    )
                ]
            ],
        )

    async def _check_kernel_update(self) -> None:
        if self._is_xpatch_active():
            return
        if not self._xkernel_path().exists():
            self.log.debug("XKernel update check skipped: core file is not installed")
            return

        try:
            update = await self._get_kernel_update_info()
        except Exception as exc:
            self.log.debug("XKernel update check failed: %s", exc)
            return

        if not update["available"]:
            return

        remote_version = update["remote_version"]
        if await self._already_notified_version(remote_version):
            return

        if self._cfg("auto_update_kernel", False):
            try:
                target_path, sha, installed_version = (
                    await self._install_latest_xkernel(
                        source=update["source"],
                        remote_version=remote_version,
                    )
                )
                await self._remember_notified_version(installed_version)
            except Exception as exc:
                self.log.exception("XKernel auto update failed")
                if self._cfg("update_notifications", True):
                    await self._send_update_notice(
                        "🚫 <b>XKernel auto update failed</b>\n"
                        f"<pre>{html.escape(str(exc))}</pre>",
                    )
                return

            if self._cfg("update_notifications", True):
                await self._send_update_notice(
                    f"{self.C['true']} <b>{self.strings('update_done_title')}</b>\n\n"
                    f"{self.strings('version_label')} <code>{self._format_version(installed_version)}</code>\n"
                    f"{self.strings('details_file_label')} <code>{html.escape(str(target_path))}</code>\n"
                    f"SHA: <code>{sha[:16]}…</code>\n\n"
                    f"{self.C['warning']} <i>{self.strings('restart_required')}</i>",
                    buttons=[
                        [
                            self.Button.inline(
                                f"{self._clear_text(self.C['reboot'])} {self.strings('btn_restart')}",
                                self.on_restart,
                                ttl=120,
                            )
                        ]
                    ],
                )
            return

        if not self._cfg("update_notifications", True):
            return

        await self._remember_notified_version(remote_version)
        await self._send_update_notice(
            f"{self.C['reload']} <b>{self.strings('update_available_title')}</b>\n\n"
            f"<blockquote>"
            f"{self.strings('local_label')} <code>{self._format_version(update['local_version'])}</code>\n"
            f"{self.strings('remote_label')} <code>{self._format_version(remote_version)}</code>"
            f"</blockquote>",
            buttons=[
                [
                    self.Button.inline(
                        f"⬆️ {self.strings('btn_update_now')}",
                        self.on_update_now,
                        ttl=300,
                    )
                ]
            ],
        )

    async def _check_manager_update(self) -> None:
        remote_version = await self._refresh_manager_update_cache()
        if not self._is_remote_newer(remote_version, self._manager_local_version()):
            return
        if await self._already_notified_manager_version(remote_version):
            return

        await self._remember_notified_manager_version(remote_version)
        await self._send_update_notice(
            f"{self.C['reload']} <b>{self.strings('manager_update_notice_title')}</b>\n\n"
            f"<blockquote>"
            f"{self.strings('local_label')} <code>{self._format_version(self._manager_local_version())}</code>\n"
            f"{self.strings('remote_label')} <code>{self._format_version(remote_version)}</code>"
            f"</blockquote>\n"
            f"{self.C['warning']} <i>{self.strings('manager_update_notice_hint')}</i>",
            buttons=[
                [
                    self.Button.url(
                        f"{self._clear_text(self.C['repo'])} {self.strings('btn_repo')}",
                        self.X_KERNEL_REPO,
                    )
                ]
            ],
        )

    async def _get_kernel_update_info(self) -> dict[str, Any]:
        source = await self._download_xkernel()
        self._validate_xkernel_source(source)
        remote_version = self._xkernel_version_from_source(source)
        local_version = self._current_xkernel_version()
        return {
            "available": self._is_remote_newer(remote_version, local_version),
            "local_version": local_version,
            "remote_version": remote_version,
            "source": source,
        }

    async def _install_latest_xkernel(
        self,
        *,
        source: str | None = None,
        remote_version: tuple[int, ...] | None = None,
    ) -> tuple[Path, str, tuple[int, ...] | None]:
        if source is None:
            source = await self._download_xkernel()
        self._validate_xkernel_source(source)
        if remote_version is None:
            remote_version = self._xkernel_version_from_source(source)

        target_path = self._xkernel_path()
        self._backup_existing(target_path)
        self._write_atomic(target_path, source)
        return target_path, self._sha256(source), remote_version

    async def _send_update_notice(self, text: str, buttons: list | None = None) -> None:
        target = getattr(self.kernel, "log_chat_id", None) or getattr(
            self.kernel, "ADMIN_ID", None
        )
        if not target:
            self.log.debug("XKernel update notice skipped: no log_chat_id/ADMIN_ID")
            return

        bot_client = getattr(self.kernel, "bot_client", None)
        if not bot_client:
            self.log.debug("XKernel update notice skipped: bot_client is unavailable")
            return

        is_authorized = getattr(bot_client, "is_user_authorized", None)
        if callable(is_authorized) and not await is_authorized():
            self.log.debug(
                "XKernel update notice skipped: bot_client is not authorized"
            )
            return

        delay = self._notification_delay_seconds()
        if delay > 0:
            await asyncio.sleep(delay)

        await bot_client.send_message(
            target,
            text,
            parse_mode="html",
            buttons=buttons,
        )

    def _current_xkernel_version(self) -> tuple[int, ...] | None:
        version = self._kernel_attr("VERSION_XKERNEL", None, protected=True)
        if isinstance(version, tuple):
            return tuple(int(part) for part in version)

        path = self._xkernel_path()
        if path.exists():
            try:
                return self._xkernel_version_from_source(
                    path.read_text(encoding="utf-8")
                )
            except OSError as exc:
                self.log.debug("Cannot read XKernel version: %s", exc)
        return None

    def _display_xkernel_version(self) -> str:
        version = self._current_xkernel_version()
        if version:
            return self._format_version(version)
        if not self._xkernel_path().exists():
            return "не установлено"
        return "unknown"

    @staticmethod
    def _xkernel_version_from_source(source: str) -> tuple[int, ...] | None:
        match = re.search(r"VERSION_XKERNEL\s*=\s*\(([^)]*)\)", source)
        if not match:
            return None
        numbers = [int(number) for number in re.findall(r"\d+", match.group(1))]
        return tuple(numbers) if numbers else None

    @staticmethod
    def _is_remote_newer(
        remote_version: tuple[int, ...] | None,
        local_version: tuple[int, ...] | None,
    ) -> bool:
        if not remote_version:
            return False
        if not local_version:
            return True
        size = max(len(remote_version), len(local_version))
        remote = remote_version + (0,) * (size - len(remote_version))
        local = local_version + (0,) * (size - len(local_version))
        return remote > local

    @staticmethod
    def _format_version(version: tuple[int, ...] | None) -> str:
        return ".".join(str(part) for part in version) if version else "unknown"

    @staticmethod
    def _coerce_dotted_version(value: Any) -> tuple[int, ...] | None:
        if value is None:
            return None
        parts = re.findall(r"\d+", str(value))
        return tuple(int(part) for part in parts) if parts else None

    def _manager_local_version(self) -> tuple[int, ...] | None:
        return self._coerce_dotted_version(getattr(self, "version", None))

    def _manager_cached_remote_version(self) -> tuple[int, ...] | None:
        return self._coerce_dotted_version(
            self._cfg("manager_remote_version_cache", None)
        )

    def _manager_update_cache_stale(self) -> bool:
        try:
            checked_at = float(self._cfg("manager_remote_version_checked_at", 0) or 0)
        except (TypeError, ValueError):
            return True
        return time.time() - checked_at >= self.MANAGER_UPDATE_CACHE_TTL

    def _manager_update_available(self) -> bool:
        return self._is_remote_newer(
            self._manager_cached_remote_version(),
            self._manager_local_version(),
        )

    async def _refresh_manager_update_cache(
        self, *, force: bool = False
    ) -> tuple[int, ...] | None:
        if not force and not self._manager_update_cache_stale():
            return self._manager_cached_remote_version()
        try:
            source = await self._download_manager()
            remote_version = self._manager_version_from_source(source)
        except Exception as exc:
            self.log.debug("XPatch manager update check failed: %s", exc)
            return self._manager_cached_remote_version()
        if remote_version:
            self.config["manager_remote_version_cache"] = self._format_version(
                remote_version
            )
            self.config["manager_remote_version_checked_at"] = str(int(time.time()))
            await self._save_config()
        return remote_version

    async def _already_notified_version(self, version: tuple[int, ...] | None) -> bool:
        if not version:
            return False
        saved = await self.db.db_get(self.name, "last_notified_xkernel_version")
        return saved == self._format_version(version)

    async def _remember_notified_version(self, version: tuple[int, ...] | None) -> None:
        if version:
            await self.db.db_set(
                self.name,
                "last_notified_xkernel_version",
                self._format_version(version),
            )

    async def _already_notified_manager_version(
        self, version: tuple[int, ...] | None
    ) -> bool:
        if not version:
            return False
        saved = await self.db.db_get(self.name, "last_notified_manager_version")
        return saved == self._format_version(version)

    async def _remember_notified_manager_version(
        self, version: tuple[int, ...] | None
    ) -> None:
        if version:
            await self.db.db_set(
                self.name,
                "last_notified_manager_version",
                self._format_version(version),
            )

    @classmethod
    def _hash_url(cls, module_name: str) -> str:
        return f"{cls.X_RAW_ROOT}/hash/{module_name}/{cls.X_HASH_FILE_NAME}"

    @classmethod
    def _extract_sha256_hash(cls, source: str) -> str:
        match = cls.SHA256_RE.search(str(source or ""))
        if match is None:
            raise ValueError("SHA256 hash file does not contain a valid digest")
        return match.group(0).casefold()

    async def _download_text(
        self, session: aiohttp.ClientSession, url: str, label: str
    ) -> str:
        async with session.get(url) as response:
            if response.status != 200:
                raise RuntimeError(f"{label} download failed: HTTP {response.status}")
            return await response.text(encoding="utf-8")

    def _verify_remote_sha256(
        self, module_name: str, source: str, hash_source: str
    ) -> str:
        expected = self._extract_sha256_hash(hash_source)
        actual = self._sha256(source)
        if actual != expected:
            raise RuntimeError(
                f"SHA256 mismatch for {module_name}: expected {expected}, got {actual}"
            )
        return actual

    async def _download_verified_module(
        self, session: aiohttp.ClientSession, module_name: str, url: str
    ) -> str:
        source = await self._download_text(session, url, module_name)
        hash_source = await self._download_text(
            session, self._hash_url(module_name), f"{module_name} SHA256"
        )
        self._verify_remote_sha256(module_name, source, hash_source)
        return source

    async def _download_xkernel(self) -> str:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            return await self._download_verified_module(
                session, "XKernel", self.X_KERNEL_URL
            )

    async def _download_manager(self) -> str:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            return await self._download_verified_module(
                session, "XPatchKernelManager", self.X_MANAGER_URL
            )

    @staticmethod
    def _manager_version_from_source(source: str) -> tuple[int, ...] | None:
        match = re.search(r"\bversion\s*=\s*[\"']([^\"']+)[\"']", source)
        if not match:
            return None
        return XKernelInstaller._coerce_dotted_version(match.group(1))

    def _validate_xkernel_source(self, source: str) -> None:
        if not source.strip():
            raise ValueError("downloaded XKernel source is empty")
        required_markers = (
            "class XPatchKernel",
            "class XPatchPatchManager",
            "Kernel = XPatchKernel",
            "from .standard import Kernel as KernelBase",
        )
        missing = [m for m in required_markers if m not in source]
        if missing:
            raise ValueError("not an expected XKernel source: " + ", ".join(missing))
        compile(source, str(self._xkernel_path()), "exec")

    def _repo_root(self) -> Path:
        import core

        return Path(core.__file__).resolve().parent.parent

    def _xkernel_path(self) -> Path:
        return self._repo_root() / "core" / "kernel" / "XKernel.py"

    def _default_core_path(self) -> Path:
        return self._repo_root() / "core" / ".default_core"

    def _get_default_core(self) -> str | None:
        path = self._default_core_path()
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8").strip() or None

    def _set_default_core(self, core_name: str) -> None:
        self._write_atomic(self._default_core_path(), f"{core_name}\n")

    def _backup_existing(self, target_path: Path) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = target_path.with_name(f"{target_path.name}.bak-{timestamp}")
        if target_path.exists():
            backup_path.write_text(
                target_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
        return backup_path

    def _backup_files(self) -> list[Path]:
        target_path = self._xkernel_path()
        return sorted(target_path.parent.glob(f"{target_path.name}.bak-*"))

    @staticmethod
    def _write_atomic(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.tmp")
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, path)

    @staticmethod
    def _sha256(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    async def _edit(self, event: Any, text: str) -> None:
        try:
            await event.edit(text, parse_mode="html")
        except Exception as exc:
            self.log.debug("cannot edit XKernelInstaller message: %s", exc)
