from __future__ import annotations

import asyncio
import contextlib
import hashlib
import html
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp

import utils
from core.lib.loader.module_base import ModuleBase, callback, command
from core.lib.loader.module_config import (
    Boolean,
    ConfigValue,
    ModuleConfig,
    Placeholders,
    String,
)
from utils.platform import get_platform_name


class XKernelInstaller(ModuleBase):
    name = "XPatchKernelManager"
    version = "1.4.0"
    author = "@Hairpin00"
    description = {
        "ru": "Менеджер и установщик XKernel core/патчей для MCUB",
        "en": "XKernel core/patch manager & installer for MCUB",
    }
    dependencies = ["aiohttp"]

    strings = {'name': 'null'}

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

    X_KERNEL_URL = (
        "https://raw.githubusercontent.com/hairpin01/XKernel/refs/heads/main/XKernel.py"
    )
    X_MANAGER_URL = (
        "https://raw.githubusercontent.com/hairpin01/XKernel/refs/heads/main/XPatchKernelManager.py"
    )
    X_KERNEL_REPO = "https://github.com/hairpin01/XKernel"
    MANAGER_UPDATE_CACHE_TTL = 6 * 60 * 60

    async def on_load(self) -> None:
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
            'бууу': '<tg-emoji emoji-id="5897962422169243693">👻</tg-emoji>',
            'on': '<tg-emoji emoji-id="5985596818912712352">✅</tg-emoji>',
            'off': '<tg-emoji emoji-id="5985346521103604145">❌</tg-emoji>',
            'v1': '<tg-emoji emoji-id="5794182096603847292">1⃣</tg-emoji>',
            'v5': '<tg-emoji emoji-id="5794066823976592976">5️⃣</tg-emoji>',
            "v10": '<tg-emoji emoji-id="5794310013614824017">1⃣</tg-emoji>',
            "magic": '<tg-emoji emoji-id="5785326857587003471">🪄</tg-emoji>',
            "utils": '<tg-emoji emoji-id="5884290437459480896">📸</tg-emoji>',
            "logs": '<tg-emoji emoji-id="5960551395730919906">📝</tg-emoji>',
            "pending": '<tg-emoji emoji-id="5839380464116175529">✏️</tg-emoji>',
            "result": '<tg-emoji emoji-id="5877540355187937244">📤</tg-emoji>',

        }
        self.C = self.CUSTOM_EMOJI
        await self._load_config()
        utils.register_decorated_placeholders(self.name, self)
        self.config["placeholders"] = utils.format_placeholders(self.name)
        await self._save_config()
        try:
            self._apply_stealth_from_config()
        except RuntimeError as exc:
            self.log.warning("Stealth mode is configured but unavailable: %s", exc)
        self._apply_experimental_from_config()
        self._apply_extera_proxy_from_config()
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
            or self._manager_update_cache_stale()
        ):
            return
        task = getattr(self, "_update_task", None)
        if task is None or task.done():
            self._update_task = asyncio.create_task(self._run_update_checks())

    async def _run_update_checks(self) -> None:
        await self._refresh_manager_update_cache()
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

        raise RuntimeError(
            "Текущее XKernel ядро не поддерживает stealth mode. "
            "Обнови XKernel и перезапусти MCUB."
        )

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
        setter(enabled)
        return True

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

    def _extera_proxy_status_label(self) -> str:
        if self._get_pm() is None:
            return "Не поддерживается текущим ядром"
        count = len(self._extera_modules_from_config())
        if bool(self._cfg("extera_proxy_all", False)):
            if count:
                return f"Принуждёный для всех, кроме {count} модуля(-лей)"
            return "Принуждёный для всех"
        if count == 0:
            return "Не активен"
        return f"Принуждёный только для {count} модуля(-лей)"

    def _clear_text(self, text) -> str:
        return  re.sub(r"<[^>]+>", "", text)

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
            body = "логи [xpatch] не найдены"
        text = (
            f"{C['logs']} <b>Live logs · [xpatch]</b>\n"
            f"<blockquote>Показывает последние <b>{max_lines}</b> строк с <code>[xpatch]</code> "
            f"из <code>logs/kernel.log</code>. Обновление: <b>{interval}</b> сек.</blockquote>\n"
            f"<code>{html.escape(str(self._kernel_log_path()))}</code>\n\n"
            f"<pre>{body}</pre>"
        )
        next_lines = self._next_live_logs_max_lines(max_lines)
        next_interval = self._next_live_logs_refresh_interval(interval)
        buttons = [
            [
                self.Button.inline(
                    f"Строк: {max_lines} → {next_lines}",
                    self.on_cycle_live_logs_lines,
                    ttl=600,
                ),
                self.Button.inline(
                    f"Обновление: {interval}с → {next_interval}с",
                    self.on_cycle_live_logs_interval,
                    ttl=600,
                ),
            ],
            [self.Button.inline(f"{self._clear_text(C['back'])} Назад", self.on_back_to_utils, ttl=600)],
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
    async def _placeholder_xkernel_version(self, data: dict[str, Any] | None = None) -> str:
        return self._display_xkernel_version()

    def _extera_proxy_scopes_label(self) -> str:
        if self._get_pm() is None:
            return "No access"
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
        stealth = "on" if self._cfg("stealth_mode", False) else "off"
        auto_update = "on" if self._cfg("auto_update_kernel", False) else "off"
        notifications = "on" if self._cfg("update_notifications", True) else "off"
        extera_proxy = html.escape(self._extera_proxy_status_label())

        if is_xpatch:
            text = (
                f"{C['settings']} <b>XPatch Manager</b>\n\n"
                f"<blockquote>"
                f"{C['true']} <b>XPatchKernel</b> <code>{xkernel_ver}</code>\n"
                f"{C['info']} <em>Version (MCUB):</em> <code>{ver}</code>\n"
                f"{C['menu']} Applied: <b>{applied}</b>  "
                f"Pending: <b>{pending}</b>  "
                f"Failed: <b>{failed}</b>"
                f"</blockquote>\n"
                f"{C['lock']} Stealth: <code>{stealth}</code>  "
                f"Auto: <code>{auto_update}</code>  "
                f"Notify: <code>{notifications}</code>\n"
                f"{C['injection']} <b>ExteraProxy Inject:</b> <i>{extera_proxy}</i>"
            )
        else:
            text = (
                f"{C['settings']} <b>XPatch Manager</b>\n\n"
                f"{C['lock']} Core: <code>{core_name}</code>\n"
                f"{C['info']} Version XPatchKernel: <code>{xkernel_ver}</code>\n\n"
                f"<blockquote>{C['warning']} <i>XPatchKernel не активен — "
                f"патчи и некоторые функции недоступны</i></blockquote>"
            )

        if self._manager_update_available():
            text += (
                f"\n\n<blockquote>{C['warning']} <b>Надо обновить XPatch Manager из репозитория, "
                f"иначе через UI нельзя будет потрогать новые фишки.</b></blockquote>"
            )

        buttons: list[list] = []

        if is_xpatch:
            buttons.append(
                [
                    self.Button.inline(
                        f"{self._clear_text(C['menu'])} Патчи", self.on_patches_menu, ttl=600
                    ),
                    self.Button.inline(
                        f"{self._clear_text(C['info'])} Подробнее", self.on_details_menu, ttl=600
                    ),
                ]
            )
            apply_row: list = [
                self.Button.inline(f"{self._clear_text(C['+'])} Apply all", self.on_apply_all, ttl=600),
            ]
            if failed:
                apply_row.append(
                    self.Button.inline(
                        f"{self._clear_text(C['off'])} {failed} failed", self.on_patches_menu, ttl=600
                    )
                )
            buttons.append(apply_row)

        buttons.append(
            [
                self.Button.inline(
                    f"{self._clear_text(C['settings'])} Настройки",
                    self.on_settings_menu,
                    ttl=600,
                ),
                self.Button.inline(f"{self._clear_text(C['reload'])} Check update", self.on_check_update, ttl=300),
                self.Button.inline(f"{self._clear_text(C['utils'])} Utils", self.on_utils_menu, ttl=600),
            ]
        )
        buttons.append(
            [
                self.Button.inline(
                    f"{self._clear_text(C['install'])} Установить / Обновить",
                    self.on_install_start,
                    ttl=600,
                ),
            ]
        )
        buttons.append(
            [
                self.Button.url("🧳 Repo", self.X_KERNEL_REPO),
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
        await self._edit(event, f"{self.C['loading']} Открываю менеджер...")
        text, buttons = self._build_main_page()
        ok, _ = await self.inline(event.chat_id, text, buttons=buttons, ttl=600)
        if not ok:
            await self._edit(event, "🚫 Не удалось открыть менеджер")
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

    def _build_utils_page(self) -> tuple[str, list]:
        C = self.C
        text = (
            f"{C['utils']} <b>XPatch Utils</b>\n\n"
            f"<blockquote>{C['logs']} <b>Live logs</b> — live-просмотр строк "
            f"<code>[xpatch]</code> из <code>logs/kernel.log</code>. "
            f"Можно выбрать лимит строк и интервал обновления.</blockquote>\n"
            f"<blockquote>{C['warning']} <b>Удаление XKernel</b> — мастер удаления ядра, "
            f"бекапов, патчей и модуля-менеджера. Можно отдельно выбрать, "
            f"сбрасывать ли default core на <code>standard</code> и делать ли авто-рестарт.</blockquote>"
        )
        buttons = [
            [self.Button.inline(f"{self._clear_text(C['logs'])} Live logs", self.on_live_logs_menu, ttl=600)],
            [self.Button.inline("🧨 Удаление XKernel", self.on_remove_xkernel_menu, ttl=600)],
            [self.Button.inline(f"{self._clear_text(C['back'])} Назад", self.on_back_to_main, ttl=600)],
        ]
        return text, buttons

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
        state = "ON" if enabled else "OFF"
        icon = self._clear_text(self.C.get("true", "✅") if enabled else self.C.get("off", "❌"))
        return f"{icon} {label}: {state}"

    def _build_remove_xkernel_page(self) -> tuple[str, list]:
        C = self.C
        options = self._xkernel_remove_options()
        text = (
            f"{C['warning']} <b>Удаление XKernel</b>\n\n"
            f"<blockquote>Выбери, что удалить. Действие необратимо для выбранных файлов. "
            f"Порядок: ядро → бэкапы → патчи → default core → менеджер → restart.</blockquote>"
        )
        buttons = [
            [self.Button.inline("🧨 Начать процесс удаления", self.on_remove_xkernel_start, ttl=300)],
            [self.Button.inline(self._toggle_text("Ядро", options["core"]), self.on_toggle_remove_option, data="core", ttl=600)],
            [self.Button.inline(self._toggle_text("Все бекапы", options["backups"]), self.on_toggle_remove_option, data="backups", ttl=600)],
            [self.Button.inline(self._toggle_text("Модуль-менеджер", options["manager"]), self.on_toggle_remove_option, data="manager", ttl=600)],
            [self.Button.inline(self._toggle_text("Все патчи", options["patches"]), self.on_toggle_remove_option, data="patches", ttl=600)],
            [self.Button.inline(self._toggle_text("Default → standard", options["default_standard"]), self.on_toggle_remove_option, data="default_standard", ttl=600)],
            [self.Button.inline(self._toggle_text("Авто-рестарт", options["restart"]), self.on_toggle_remove_option, data="restart", ttl=600)],
            [self.Button.inline(f"{self._clear_text(C['back'])} Назад", self.on_back_to_utils, ttl=600)],
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
                lines.append(f"✅ Ядро удалено: <code>{html.escape(str(target))}</code>")
            else:
                lines.append("ℹ️ Ядро уже отсутствует")

        if options.get("backups", False):
            backups = self._backup_files()
            for backup in backups:
                backup.unlink(missing_ok=True)
            lines.append(f"✅ Бекапы удалены: <b>{len(backups)}</b>")

        if options.get("patches", False):
            patches_dir = self._patches_dir_path()
            if patches_dir.exists():
                shutil.rmtree(patches_dir)
                lines.append(f"✅ Патчи удалены: <code>{html.escape(str(patches_dir))}</code>")
            else:
                lines.append("ℹ️ Папка патчей уже отсутствует")

        if options.get("default_standard", False):
            self._set_default_core("standard")
            lines.append("✅ Default core установлен: <code>standard</code>")

        if options.get("manager", False):
            await self.invoke("um", args=self.name, chat_id="me")
            lines.append("✅ Запрошено удаление модуля-менеджера")

        if options.get("restart", False):
            await self.invoke("restart", chat_id="me")
            lines.append("✅ Запрошен рестарт MCUB")

        return lines or ["ℹ️ Ничего не выбрано"]

    @callback(ttl=300)
    async def on_remove_xkernel_start(self, call) -> None:
        options = dict(self._xkernel_remove_options())
        await call.answer("Удаляю XKernel...", alert=False)
        try:
            lines = await self._execute_xkernel_removal(options)
        except Exception as exc:
            self.log.exception("XKernel removal failed")
            await call.edit(
                f"{self.C['off']} <b>Удаление XKernel сорвалось</b>\n\n"
                f"<blockquote><code>{html.escape(str(exc))}</code></blockquote>",
                buttons=[[self.Button.inline(f"{self._clear_text(self.C['back'])} Назад", self.on_remove_xkernel_menu, ttl=600)]],
            )
            return

        await call.edit(
            f"{self.C['true']} <b>Удаление XKernel завершено</b>\n\n<blockquote>"
            + "\n".join(lines)
            + "</blockquote>",
            buttons=[[self.Button.inline(f"{self._clear_text(self.C['back'])} Назад", self.on_utils_menu, ttl=600)]],
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

    async def _set_live_logs_max_lines(self, call: Any, value: int) -> None:
        self.config["live_logs_max_lines"] = str(value)
        await self._save_config()
        await call.answer(f"Live logs: {value} строк", alert=False)
        self._live_logs_event = call
        await self._refresh_live_logs()

    async def _set_live_logs_refresh_interval(self, call: Any, value: int) -> None:
        self.config["live_logs_refresh_interval"] = str(value)
        await self._save_config()
        await call.answer(f"Live logs: обновление {value} сек", alert=False)
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
            f"{C['settings']} <b>XPatch настройки</b>\n\n"
            f"{self._bool_icon(stealth)} <b>Stealth mode</b>\n"
            f"<blockquote><em>{C['бууу']} VERSION без .XPatch, без VERSION_XKERNEL/ver, CORE_NAME=standard</em></blockquote>\n"
            f"{self._bool_icon(auto_update)} <b>Auto update ядра</b>\n"
            f"<blockquote><em>{C['info']} Если VERSION_XKERNEL стал выше — ставить сразу</em></blockquote>\n"
            f"{self._bool_icon(notifications)} <b>Уведомления об обновлении</b>\n"
            f"<blockquote><em>{C['diskette']} Бот пишет в лог-чат или в ЛС клиенту</em></blockquote>"
        )
        buttons = [
            [
                self.Button.inline(
                    f"Stealth: {'ON' if stealth else 'OFF'}",
                    self.on_toggle_stealth,
                    ttl=600,
                    style='danger' if not stealth else 'success',
                )
            ],
            [
                self.Button.inline(
                    f"Auto update: {'ON' if auto_update else 'OFF'}",
                    self.on_toggle_auto_update,
                    ttl=600,
                    style='danger' if not auto_update else 'success',
                )
            ],
            [
                self.Button.inline(
                    f"Notify: {'ON' if notifications else 'OFF'}",
                    self.on_toggle_notifications,
                    ttl=600,
                    style='danger' if not notifications else 'success',
                )
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['injection'])} ExteraProxy Inject",
                    self.on_extera_proxy_menu,
                    ttl=600,
                    style='primary',
                )
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['magic'] if self._get_pm() is not None else C['warning'])} Экспериментальные функции",
                    self.on_experimental_settings_menu,
                    ttl=600,
                    style='primary' if self._get_pm() is not None else 'danger',
                )
            ],
            [self.Button.inline(f"{self._clear_text(C['back'])} Назад", self.on_back_to_main, ttl=600)],
        ]
        return text, buttons

    def _bool_icon(self, value: bool) -> str:
        return self.C['on'] if value else self.C['off']

    @callback(ttl=600)
    async def on_settings_menu(self, call) -> None:
        text, buttons = self._build_settings_page()
        await call.edit(text, buttons=buttons)

    def _build_extera_proxy_page(self) -> tuple[str, list]:
        C = self.C
        supported = self._get_pm() is not None
        all_enabled = bool(self._cfg("extera_proxy_all", False))
        modules = self._extera_modules_from_config()
        modules_text = ", ".join(html.escape(item) for item in modules) or "нет"
        scopes = self._extera_scopes_from_config()
        root_enabled = "root" in scopes
        scopes_text = self._extera_proxy_scopes_label() if supported else "No access"
        modules_label = "Исключения" if all_enabled else "Выбранные модули"
        status = html.escape(
            self._extera_proxy_status_label()
            if supported
            else "Не поддерживается текущим ядром"
        )
        status_icon = C["moon"] if supported else C["warning"]
        text = (
            f"{C['injection']} <b>ExteraProxy Inject</b>\n"
            f"<blockquote>{C['info']} Что это? Можно сказать патчит ядро так, что оно <b>даёт Root модулю. Доступ к ядру/клиенту или событию</b>, нужно только если модуль требует защищённый объект (например, session у client)</blockquote>\n"
            f"<blockquote>{C['warning']} Если вы не знаете зачем это вам - <b>не трогайте</b></blockquote>\n"
            f"{status_icon} Статус: <b>{status}</b>\n"
            f"{C['command']} <b>Scopes:</b> <code>{html.escape(scopes_text)}</code>\n"
            f"{C['info']} {modules_label}: <code>{modules_text}</code>\n"
            f"<blockquote expandable>{C['warning']} <b>Включай только для известных и доверенных модулей. "
            f"Не включай для неизвестных или подозрительных модулей.</b></blockquote>"
        )
        if not supported:
            return text, [[self.Button.inline(f"{self._clear_text(C['back'])} Назад", self.on_settings_menu, ttl=600)]]
        buttons = [
            [
                self.Button.inline(
                    f"Для всех: {'ON' if all_enabled else 'OFF'}",
                    self.on_toggle_extera_proxy_all,
                    ttl=600,
                    style='danger' if not all_enabled else "success",
                )
            ],
            (
                [
                    self.Button.inline(
                        "Root: ON → custom",
                        self.on_toggle_extera_scope_root,
                        ttl=600,
                        style='success'
                    )
                ]
                if root_enabled
                else [
                    self.Button.inline(
                        f"Kernel: {'ON' if 'kernel' in scopes else 'OFF'}",
                        self.on_toggle_extera_scope_kernel,
                        ttl=600,
                        style='danger' if not 'kernel' in scopes else 'success',
                    ),
                    self.Button.inline(
                        f"Client: {'ON' if 'client' in scopes else 'OFF'}",
                        self.on_toggle_extera_scope_client,
                        ttl=600,
                        style='danger' if not 'client' in scopes else 'success',
                    ),
                    self.Button.inline(
                        f"Event: {'ON' if 'event' in scopes else 'OFF'}",
                        self.on_toggle_extera_scope_event,
                        ttl=600,
                        style='danger' if not 'event' in scopes else 'success'
                    ),
                ]
            ),
            [
                self.Button.input(
                    f"{self._clear_text(C['+'])} Добавить модуль",
                    self.on_extera_proxy_add_input,
                    placeholder="ModuleName",
                    ttl=600,
                    style='success'
                ),
                self.Button.input(
                    "➖ Убрать модуль",
                    self.on_extera_proxy_remove_input,
                    placeholder="ModuleName",
                    ttl=600,
                    style='danger'
                ),
            ],
            [
                self.Button.inline(
                    "🧹 Очистить список",
                    self.on_clear_extera_proxy_modules,
                    ttl=600,
                )
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['back'])} Назад",
                    self.on_settings_menu,
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

    def _build_experimental_settings_page(self) -> tuple[str, list]:
        C = self.C
        patch_events = bool(self._cfg("experimental_patch_events", False))
        hot_reload = bool(self._cfg("experimental_patch_hot_reload", False))
        text = (
            f"{C['magic']} <b>Экспериментальные функции XPatch</b>\n\n"
            f"{self._bool_icon(patch_events)} <b>Patch events</b>\n"
            f"<blockquote><em>{C['injection']} emit xpatch:applied / xpatch:failed / xpatch:unapplied</em></blockquote>\n"
            f"{self._bool_icon(hot_reload)} <b>Hot reload патчей</b>\n"
            f"<blockquote><em>{C['reload']} следит за файлами patches/*.py и перезагружает изменённые</em></blockquote>\n"
            f"<blockquote>{C['warning']} <i>Функции экспериментальные: включай только если понимаешь риски.</i></blockquote>"
        )
        buttons = [
            [
                self.Button.inline(
                    f"Patch events: {'ON' if patch_events else 'OFF'}",
                    self.on_toggle_patch_events,
                    ttl=600,
                    style='danger' if not patch_events else 'success',
                )
            ],
            [
                self.Button.inline(
                    f"Hot reload: {'ON' if hot_reload else 'OFF'}",
                    self.on_toggle_patch_hot_reload,
                    ttl=600,
                    style='danger' if not hot_reload else 'success',
                )
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['back'])} Назад",
                    self.on_settings_menu,
                    ttl=600,
                )
            ],
        ]
        return text, buttons

    @callback(ttl=600)
    async def on_experimental_settings_menu(self, call) -> None:
        if self._get_pm() is None:
            await call.answer("Не поддерживается текущим ядром", alert=True)
            await call.edit(
                f"{self.C['warning']} <b>Экспериментальные функции недоступны</b>\n\n"
                f"<blockquote>Текущее ядро не поддерживает runtime-функции XKernel.</blockquote>",
                buttons=[[self.Button.inline(f"{self._clear_text(self.C['back'])} Назад", self.on_settings_menu, ttl=600)]],
            )
            return
        text, buttons = self._build_experimental_settings_page()
        await call.edit(text, buttons=buttons)

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
            await call.answer("Stealth включён", alert=False)
        else:
            self.config["stealth_mode"] = False
            self._disable_runtime_stealth()
            await self._save_config()
            await call.answer("Stealth выключен", alert=False)
        text, buttons = self._build_settings_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_toggle_auto_update(self, call) -> None:
        new_value = not bool(self._cfg("auto_update_kernel", False))
        self.config["auto_update_kernel"] = new_value
        await self._save_config()
        self._ensure_update_task()
        await call.answer(f"Auto update: {'ON' if new_value else 'OFF'}", alert=False)
        text, buttons = self._build_settings_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_toggle_notifications(self, call) -> None:
        new_value = not bool(self._cfg("update_notifications", True))
        self.config["update_notifications"] = new_value
        await self._save_config()
        self._ensure_update_task()
        await call.answer(f"Уведомления: {'ON' if new_value else 'OFF'}", alert=False)
        text, buttons = self._build_settings_page()
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
            await call.answer("Текущее XKernel ядро не поддерживает ExteraProxy scopes", alert=True)
            return
        await self._save_config()
        await call.answer(f"ExteraProxy {scope}: {'ON' if scope in scopes else 'OFF'}", alert=False)
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
            await call.answer("Текущее XKernel ядро не поддерживает ExteraProxy", alert=True)
            return
        if not new_value:
            self._set_runtime_extera_proxy_all(False)
        self.config["extera_proxy_all"] = new_value
        await self._save_config()
        await call.answer(
            "ExteraProxy для всех включён. Осторожно: только для доверенных модулей!"
            if new_value else "ExteraProxy для всех выключен",
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
            await self._edit(event, "🚫 Укажи имя модуля")
            return
        modules = self._extera_modules_from_config()
        if module_name.casefold() not in {item.casefold() for item in modules}:
            modules.append(module_name)
        self._save_extera_modules_to_config(modules)
        if not self._set_runtime_extera_proxy_modules(modules):
            await self._edit(event, "🚫 Текущее XKernel ядро не поддерживает ExteraProxy")
            return
        await self._save_config()
        await self._refresh_extera_proxy_event()
        await self._edit(
            event,
            f"{self.C['warning']} <b>ExteraProxy добавлен</b>\n"
            f"Модуль: <code>{html.escape(module_name)}</code>\n\n"
            f"<blockquote><em>Отключение core-proxy опасно для неизвестных/подозрительных модулей.</em></blockquote>",
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
            f"{self.C['true']} ExteraProxy удалён для <code>{html.escape(module_name or 'unknown')}</code>",
        )

    @callback(ttl=600)
    async def on_clear_extera_proxy_modules(self, call) -> None:
        self._extera_proxy_event = call
        self._save_extera_modules_to_config([])
        self._set_runtime_extera_proxy_modules([])
        await self._save_config()
        await call.answer("Список ExteraProxy очищен", alert=False)
        text, buttons = self._build_extera_proxy_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_toggle_patch_events(self, call) -> None:
        new_value = not bool(self._cfg("experimental_patch_events", False))
        if new_value and not self._set_runtime_patch_events(True):
            await call.answer("Текущее XKernel ядро не поддерживает patch events", alert=True)
            return
        if not new_value:
            self._set_runtime_patch_events(False)
        self.config["experimental_patch_events"] = new_value
        await self._save_config()
        await call.answer(f"Patch events: {'ON' if new_value else 'OFF'}", alert=False)
        text, buttons = self._build_experimental_settings_page()
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_toggle_patch_hot_reload(self, call) -> None:
        new_value = not bool(self._cfg("experimental_patch_hot_reload", False))
        if new_value and not self._set_runtime_hot_reload(True):
            await call.answer("Текущее XKernel ядро не поддерживает hot reload", alert=True)
            return
        if not new_value:
            self._set_runtime_hot_reload(False)
        self.config["experimental_patch_hot_reload"] = new_value
        await self._save_config()
        await call.answer(f"Hot reload: {'ON' if new_value else 'OFF'}", alert=False)
        text, buttons = self._build_experimental_settings_page()
        await call.edit(text, buttons=buttons)

    def _patch_button_entries(self, pm: Any) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        def add(patch_key: str, target: str, status: str) -> None:
            target_text = str(target)
            entry_key = (patch_key, self._patch_target_norm(pm, target_text))
            if entry_key in seen:
                return
            seen.add(entry_key)
            entries.append({"patch_key": patch_key, "target": target_text, "status": status})

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
        return normalize(target) if callable(normalize) else str(target).strip().casefold()

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
        info["disabled"] = bool(is_disabled(patch_key)) if callable(is_disabled) else False
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
                info["version_ok"] = not bool(version_less(current, required)) if callable(version_less) else True
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
            f"{self.C['menu']} <b>Patch detail</b>",
            "",
            f"{self._patch_status_icon(str(info['status']))} Status: <b>{html.escape(str(info['status']))}</b>",
            f"<blockquote expandable>Patch: <code>{html.escape(str(info['name']))}</code>",
            f"Target: <code>{html.escape(str(info['target']))}</code>",
            f"File: <code>{html.escape(str(info['file']))}</code>",
            f"Key: <code>{html.escape(str(info['patch_key']))}</code></blockquote>",
        ]
        if result:
            lines += [
                "",
                f"<blockquote expandable>{self.C['result']} <b>Result</b>\n<code>{html.escape(result)}</code></blockquote>",
            ]
        if pending_reason:
            lines += [
                "",
                f"<blockquote expandable>{self.C['pending']} <b>Pending reason</b>\n<code>{html.escape(pending_reason)}</code></blockquote>",
            ]
        if error:
            lines += [
                "",
                f"<blockquote expandable>{self.C['off']} <b>Error</b>\n{html.escape(error)}</blockquote>",
            ]
        if full_traceback:
            lines += [
                "",
                f"<blockquote expandable>{self.C['logs']} <b>Traceback</b>\n<code>{html.escape(full_traceback)}</code></blockquote>",
            ]
        if version_known and not version_ok:
            lines += [
                "",
                f"<blockquote>{self.C['warning']} <b>Минимальная версия XKernel для этого патча: {html.escape(required_xkernel)}</b></blockquote>",
            ]
        elif version_known:
            lines += [
                "",
                f"<blockquote>{self.C['on']} <b>Патч совместим с текущей версией XKernel</b></blockquote>",
            ]
        else:
            lines += [
                "",
                f"<blockquote>{self.C['warning']} <b>Минимальная версия XKernel для этого патча не указана</b></blockquote>",
            ]
        return "\n".join(lines)

    @callback(ttl=600)
    async def on_patches_menu(self, call) -> None:
        C = self.C
        pm = self._get_pm()
        if pm is None:
            await call.answer("XPatchKernel не активен", alert=True)
            return

        applied = len(pm.applied_patches)
        pending = sum(len(v) for v in pm.pending_patches.values())
        failed = len(pm.failed_patches)
        disabled = len(getattr(pm, "disabled_patches", set()) or set())
        text = (
            f"{C['menu']} <b>Патчи</b>\n\n"
            f"{C['true']} Applied: <b>{applied}</b>  "
            f"{C['pending']} Pending: <b>{pending}</b>  "
            f"{C['off']} Failed: <b>{failed}</b>  "
            f"{C['warning']} Disabled: <b>{disabled}</b>\n"
            f"<blockquote>Нажми на патч, чтобы открыть детали.</blockquote>"
        )

        buttons: list[list] = []
        for entry in self._patch_button_entries(pm):
            info = self._patch_detail_info(pm, entry)
            label = (
                f"{self._clear_text(self._patch_status_icon(str(info['status'])))} "
                f"{str(info['name'])[:32]} → {str(info['target'])[:24]}"
            )
            buttons.append([self.Button.inline(label, self.on_patch_detail, data=entry, ttl=600)])

        if not buttons:
            text += "\n\n<i>Патчи не найдены</i>"
        buttons.append([self.Button.inline(f"{self._clear_text(C['back'])} Назад", self.on_back_to_main, ttl=600)])
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_patch_detail(self, call, data: Any = None) -> None:
        pm = self._get_pm()
        if pm is None:
            await call.answer("XPatchKernel не активен", alert=True)
            return
        info = self._patch_detail_info(pm, data)
        buttons: list[list] = []
        buttons.append([self.Button.inline("🔁 Reload patch", self.on_patch_reload, data=data, ttl=600)])
        if info["disabled"]:
            buttons.append([self.Button.inline("✅ Enable patch", self.on_patch_enable, data=data, ttl=600)])
        else:
            buttons.append([self.Button.inline("🚫 Disable patch", self.on_patch_disable, data=data, ttl=600)])
        if info["status"] == "applied" and info.get("has_unapply"):
            buttons.append([self.Button.inline("↩️ Unapply", self.on_patch_unapply, data=data, ttl=600)])
        if info["status"] == "failed" and str(info["target"]) not in {"<load>", "<missing-target>"}:
            buttons.append([self.Button.inline("🔁 Retry", self.on_patch_retry, data=data, ttl=600)])
        buttons.append([self.Button.inline(f"{self._clear_text(self.C['back'])} Назад", self.on_patches_menu, ttl=600)])
        await call.edit(self._patch_detail_text(info), buttons=buttons)

    @callback(ttl=600)
    async def on_patch_reload(self, call, data: Any = None) -> None:
        pm = self._get_pm()
        if pm is None:
            await call.answer("XPatchKernel не активен", alert=True)
            return
        patch_key = str((data or {}).get("patch_key", ""))
        reload_patch_key = getattr(pm, "reload_patch_key", None)
        if not callable(reload_patch_key):
            await call.answer("Это XKernel ядро не поддерживает reload одного патча", alert=True)
            return
        result = await reload_patch_key(patch_key)
        if result.get("failed"):
            await call.answer("Reload failed", alert=True)
        elif result.get("missing"):
            await call.answer("Patch file not found", alert=True)
        else:
            await call.answer("Reloaded", alert=False)
        await self.on_patch_detail(call, data)

    @callback(ttl=600)
    async def on_patch_unapply(self, call, data: Any = None) -> None:
        pm = self._get_pm()
        if pm is None:
            await call.answer("XPatchKernel не активен", alert=True)
            return
        patch_key = str((data or {}).get("patch_key", ""))
        target = str((data or {}).get("target", ""))
        result = await pm.unapply_patch(patch_key, target)
        await call.answer(f"Unapply: {result}", alert=result == "failed")
        await self.on_patch_detail(call, data)

    async def _set_patch_disabled_from_detail(self, call, data: Any, disabled: bool) -> None:
        pm = self._get_pm()
        if pm is None:
            await call.answer("XPatchKernel не активен", alert=True)
            return
        patch_key = str((data or {}).get("patch_key", ""))
        setter = getattr(pm, "set_patch_disabled", None)
        if not callable(setter):
            await call.answer("Это XKernel ядро не поддерживает enable/disable патчей", alert=True)
            return
        setter(patch_key, disabled)
        if disabled:
            await pm.unapply_patch_key(patch_key)
            await call.answer("Patch disabled", alert=False)
        else:
            await pm.apply_all(force=True)
            await call.answer("Patch enabled", alert=False)
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
            await call.answer("XPatchKernel не активен", alert=True)
            return
        info = self._patch_detail_info(pm, data)
        target = str(info.get("target") or "")
        await call.answer("Retry patch...", alert=False)
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
                f"{C['file']} Файл: <code>{html.escape(str(target_path))}</code>",
                f"{C['lock']} SHA256: <code>{sha[:16]}…</code>",
                f"{C['dir']} Размер: <code>{size_kb:.1f} KB</code>",
                f"{C['diskette']} Бэкапов: <code>{len(backups)}</code>",
                "",
            ]
        else:
            lines += [
                f"{C['warning']} XKernel не найден:",
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
            f"{C['lock']} Default core: <code>{html.escape(default_core or 'не задан')}</code>",
            f"{C['pc']} Platform: <code>{html.escape(get_platform_name())}</code>",
        ]

        text = f"{C['info']} <b>XKernel · Подробно</b>\n\n<blockquote>" + "\n".join(lines) + "</blockquote>"
        buttons = [
            [
                self.Button.inline(f"{self._clear_text(C['back'])} Назад", self.on_back_to_main, ttl=600),
                self.Button.inline("⏪ Rollback", self.on_rollback_confirm, ttl=300),
            ],
        ]
        await call.edit(text, buttons=buttons)

    @callback(ttl=600)
    async def on_install_start(self, call) -> None:
        C = self.C
        await call.edit(
            f"{C['install']} <b>Загружаю XKernel...</b>\n"
            f"{C['moon']} Платформа: <code>{html.escape(get_platform_name())}</code>",
        )
        try:
            source = await self._download_xkernel()
            self._validate_xkernel_source(source)

            target_path = self._xkernel_path()
            self._backup_existing(target_path)
            self._write_atomic(target_path, source)
            sha = self._sha256(source)

            text = (
                f"{C['true']} <b>XKernel установлен</b>\n\n"
                f"<blockquote>"
                f"{C['file']} Файл: <code>{html.escape(str(target_path))}</code>\n"
                f"{C['lock']} SHA: <code>{sha[:16]}…</code>"
                f"</blockquote>\n"
                f"{C['warning']} <b>Сделать XKernel ядром по умолчанию?</b>\n"
                f"<blockquote>Если выбрать да, MCUB будет стартовать с XKernel без ручного <code>--core XKernel</code>.</blockquote>"
            )
            buttons = [
                [
                    self.Button.inline(
                        "✅ Установить по дефолту",
                        self.on_install_set_default,
                        ttl=300,
                    ),
                    self.Button.inline(
                        "Нет, спасибо",
                        self.on_install_skip_default,
                        ttl=300,
                    ),
                ],
            ]
        except Exception as exc:
            self.log.exception("XKernel inline install failed")
            text = f"🚫 <b>Ошибка установки</b>\n" f"<pre>{html.escape(str(exc))}</pre>"
            buttons = [
                [
                    self.Button.inline(
                        f"{self._clear_text(C['back'])} Назад", self.on_back_to_main, ttl=600
                    )
                ],
            ]
        await call.edit(text, buttons=buttons)

    def _install_finish_page(self, default_changed: bool) -> tuple[str, list]:
        C = self.C
        default_text = "XKernel" if default_changed else "не менял"
        text = (
            f"{C['true']} <b>Готово</b>\n\n"
            f"<blockquote>{C['lock']} Default core: <code>{html.escape(default_text)}</code></blockquote>\n"
            f"{C['warning']} <i>Нужен рестарт MCUB</i>"
        )
        buttons = [
            [
                self.Button.inline(
                    f"{self._clear_text(C['reboot'])} Рестарт", self.on_restart, ttl=120
                ),
                self.Button.inline(
                    f"{self._clear_text(C['back'])} Назад", self.on_back_to_main, ttl=600
                ),
            ],
        ]
        return text, buttons

    @callback(ttl=300)
    async def on_install_set_default(self, call) -> None:
        self._set_default_core("XKernel")
        await call.answer("XKernel установлен по умолчанию", alert=False)
        text, buttons = self._install_finish_page(default_changed=True)
        await call.edit(text, buttons=buttons)

    @callback(ttl=300)
    async def on_install_skip_default(self, call) -> None:
        await call.answer("Default core не менял", alert=False)
        text, buttons = self._install_finish_page(default_changed=False)
        await call.edit(text, buttons=buttons)

    @callback(ttl=300)
    async def on_check_update(self, call) -> None:
        await call.answer("Проверяю XKernel...", alert=False)
        try:
            update = await self._get_kernel_update_info()
        except Exception as exc:
            self.log.exception("XKernel update check failed")
            await call.edit(
                f"🚫 <b>Update check failed</b>\n<pre>{html.escape(str(exc))}</pre>",
                buttons=[[self.Button.inline(f"{self._clear_text(self.C['back'])} Назад", self.on_back_to_main, ttl=600)]],
            )
            return

        if not update["available"]:
            await call.edit(
                f"{self.C['true']} <b>XKernel уже актуален</b>\n\n"
                f"<blockquote>"
                f"Local: <code>{self._format_version(update['local_version'])}</code>\n"
                f"Remote: <code>{self._format_version(update['remote_version'])}</code>"
                f"</blockquote>",
                buttons=[[self.Button.inline(f"{self._clear_text(self.C['back'])} Назад", self.on_back_to_main, ttl=600)]],
            )
            return

        await call.edit(
            f"{self.C['reload']} <b>Доступно обновление XKernel</b>\n\n"
            f"<blockquote>"
            f"Local: <code>{self._format_version(update['local_version'])}</code>\n"
            f"Remote: <code>{self._format_version(update['remote_version'])}</code>"
            f"</blockquote>",
            buttons=[
                [
                    self.Button.inline("⬆️ Обновиться", self.on_update_now, ttl=300),
                    self.Button.inline(f"{self._clear_text(self.C['back'])} Назад", self.on_back_to_main, ttl=600),
                ]
            ],
        )

    @callback(ttl=300)
    async def on_update_now(self, call) -> None:
        C = self.C
        await call.edit(f"{C['loading']} <b>Обновляю XKernel...</b>")
        try:
            target_path, sha, remote_version = await self._install_latest_xkernel()
            await self._remember_notified_version(remote_version)
        except Exception as exc:
            self.log.exception("XKernel update install failed")
            await call.edit(
                f"🚫 <b>XKernel не обновлён</b>\n"
                f"<pre>{html.escape(str(exc))}</pre>\n\n"
                f"Открой менеджер заново: <code>.xm</code>",
            )
            return

        await call.edit(
            f"{C['true']} <b>XKernel обновлён</b>\n\n"
            f"<blockquote>"
            f"Version: <code>{self._format_version(remote_version)}</code>\n"
            f"{C['file']} Файл: <code>{html.escape(str(target_path))}</code>\n"
            f"{C['lock']} SHA: <code>{sha[:16]}…</code>"
            f"</blockquote>\n"
            f"{C['warning']} <i>Нужен рестарт MCUB</i>\n"
            f"<em>Открой менеджер заново:</em> <code>.xm</code>",
        )

    @callback(ttl=600)
    async def on_apply_all(self, call) -> None:
        C = self.C
        pm = self._get_pm()
        if pm is None:
            await call.answer("XPatchKernel не активен", alert=True)
            return

        await call.edit(
            f"{C['loading']} <b>Применяю патчи...</b>",
        )
        try:
            result = await pm.apply_all()
        except Exception as exc:
            self.log.exception("apply_patches failed")
            await call.edit(
                f"🚫 <b>Ошибка apply_patches</b>\n<pre>{html.escape(str(exc))}</pre>",
                buttons=[
                    [
                        self.Button.inline(
                            f"{self._clear_text(C['back'])} Назад", self.on_back_to_main, ttl=600
                        )
                    ]
                ],
            )
            return

        applied = result.get("applied", [])
        pending = result.get("pending", [])
        failed = result.get("failed", [])
        skipped = result.get("skipped", [])

        lines: list[str] = [f"{C['settings']} <b>Apply all — результат</b>\n"]
        if applied:
            lines.append(f"{C['true']} Applied ({len(applied)}):")
            for name, tgt in applied:
                lines.append(
                    f"  <code>{html.escape(name)}</code> → <i>{html.escape(tgt)}</i>"
                )
        if pending:
            lines.append(f"\n{C['pending']} Pending ({len(pending)}):")
            for name, tgt in pending:
                lines.append(
                    f"  <code>{html.escape(name)}</code> → <i>{html.escape(tgt)}</i>"
                )
        if failed:
            lines.append(f"\n{C['off']} Failed ({len(failed)}):")
            for name, tgt in failed:
                lines.append(
                    f"  <code>{html.escape(name)}</code> → <i>{html.escape(tgt)}</i>"
                )
        if skipped:
            lines.append(f"\n⏭ Skipped: {len(skipped)}")

        needs_restart = bool(applied)
        if needs_restart:
            lines.append(f"\n{C['warning']} <i>Нужен рестарт для применения патчей</i>")

        text = "<blockquote expandable>" + "\n".join(lines) + "</blockquote>"
        back_btn = self.Button.inline(
            f"{self._clear_text(C['back'])} Назад", self.on_back_to_main, ttl=600
        )
        buttons = (
            [
                [
                    self.Button.inline(
                        f"{self._clear_text(C['reboot'])} Рестарт", self.on_restart, ttl=120
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
            await call.answer("Backup не найден", alert=True)
            return

        latest = backups[-1]
        text = (
            f"⏪ <b>Rollback — подтверждение</b>\n\n"
            f"Будет восстановлен:\n"
            f"<blockquote><code>{html.escape(str(latest))}</code></blockquote>\n"
            f"{C['warning']} <i>Нужен рестарт после отката</i>"
        )
        buttons = [
            [
                self.Button.inline(f"{self._clear_text(self.C['true'])} Откатить", self.on_rollback_do, ttl=120),
                self.Button.inline(
                    f"{self._clear_text(C['back'])} Отмена", self.on_details_menu, ttl=300
                ),
            ],
        ]
        await call.edit(text, buttons=buttons)

    @callback(ttl=120)
    async def on_rollback_do(self, call) -> None:
        C = self.C
        backups = self._backup_files()
        if not backups:
            await call.answer("Backup не найден", alert=True)
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
                f"🚫 <b>Rollback не выполнен</b>\n<pre>{html.escape(str(exc))}</pre>",
                buttons=[
                    [
                        self.Button.inline(
                            f"{self._clear_text(C['back'])} Назад", self.on_back_to_main, ttl=600
                        )
                    ]
                ],
            )
            return

        text = (
            f"{C['true']} <b>Rollback выполнен</b>\n\n"
            f"<blockquote>Восстановлен: <code>{html.escape(str(latest_backup))}</code></blockquote>\n"
            f"{C['warning']} <i>Нужен рестарт MCUB</i>"
        )
        buttons = [
            [
                self.Button.inline(f"{self._clear_text(C['reboot'])} Рестарт", self.on_restart, ttl=120),
                self.Button.inline(f"{self._clear_text(C['back'])} Назад", self.on_back_to_main, ttl=600),
            ],
        ]
        await call.edit(text, buttons=buttons)

    @callback(ttl=120)
    async def on_restart(self, call) -> None:
        await call.answer("Ребутаю MCUB...", alert=False)
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
            f"{C['install']} <b>Начинаю ставить XPatchKernel</b>\n"
            f"{C['moon']} Платформа: <code>{html.escape(get_platform_name())}</code>",
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
                f"{C['true']} <b>XKernel установлен/обновлён</b>\n\n"
                f"<blockquote>"
                f"{C['file']} Файл: <code>{html.escape(str(target_path))}</code>\n"
                f"{C['lock']} SHA: <code>{sha[:16]}…</code>\n"
                f"{C['diskette']} Default core: "
                f"<code>{'XKernel' if default_changed else 'не менял'}</code>"
                f"</blockquote>\n"
                f"{C['warning']} <i>Нужен рестарт MCUB</i>",
            )
            await self._show_restart_prompt(event)

        except Exception as exc:
            self.log.exception("XKernel install failed")
            await self._edit(
                event,
                f"🚫 <b>XKernel не установлен</b>\n<pre>{html.escape(str(exc))}</pre>",
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
            await self._edit(event, f"{C['warning']} <b>Backup для XKernel не найден</b>")
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
                f"🚫 <b>Rollback не выполнен</b>\n<code>{html.escape(str(exc))}</code>",
            )
            return

        await self._edit(
            event,
            f"{C['true']} <b>XKernel rollback выполнен</b>\n\n"
            f"<blockquote>Восстановлен: <code>{html.escape(str(latest_backup))}</code></blockquote>\n"
            f"{C['warning']} <i>Ребутни MCUB</i>",
        )
        await self._show_restart_prompt(event)

    async def _show_restart_prompt(self, event: Any) -> None:
        C = self.C
        await self.inline(
            event.chat_id,
            "Рестарт MCUB?",
            buttons=[
                [self.Button.inline(f"{self._clear_text(C['reboot'])} Reboot", self.on_restart, ttl=120)]
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
                target_path, sha, installed_version = await self._install_latest_xkernel(
                    source=update["source"],
                    remote_version=remote_version,
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
                    f"{self.C['true']} <b>XKernel auto updated</b>\n\n"
                    f"Version: <code>{self._format_version(installed_version)}</code>\n"
                    f"File: <code>{html.escape(str(target_path))}</code>\n"
                    f"SHA: <code>{sha[:16]}…</code>\n\n"
                    f"{self.C['warning']} <i>Нужен рестарт MCUB</i>",
                    buttons=[
                        [
                            self.Button.inline(
                                f"{self._clear_text(self.C['reboot'])} Рестарт",
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
            f"{self.C['reload']} <b>Доступно обновление XKernel</b>\n\n"
            f"<blockquote>"
            f"Local: <code>{self._format_version(update['local_version'])}</code>\n"
            f"Remote: <code>{self._format_version(remote_version)}</code>"
            f"</blockquote>",
            buttons=[[self.Button.inline("⬆️ Обновиться", self.on_update_now, ttl=300)]],
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
            self.log.debug("XKernel update notice skipped: bot_client is not authorized")
            return

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

    async def _refresh_manager_update_cache(self, *, force: bool = False) -> tuple[int, ...] | None:
        if not force and not self._manager_update_cache_stale():
            return self._manager_cached_remote_version()
        try:
            source = await self._download_manager()
            remote_version = self._manager_version_from_source(source)
        except Exception as exc:
            self.log.debug("XPatch manager update check failed: %s", exc)
            return self._manager_cached_remote_version()
        if remote_version:
            self.config["manager_remote_version_cache"] = self._format_version(remote_version)
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

    async def _download_xkernel(self) -> str:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(self.X_KERNEL_URL) as response:
                if response.status != 200:
                    raise RuntimeError(f"download failed: HTTP {response.status}")
                return await response.text(encoding="utf-8")

    async def _download_manager(self) -> str:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(self.X_MANAGER_URL) as response:
                if response.status != 200:
                    raise RuntimeError(f"manager download failed: HTTP {response.status}")
                return await response.text(encoding="utf-8")

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
