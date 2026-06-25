from __future__ import annotations

import asyncio
import contextlib
import hashlib
import html
import os
import re
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
    X_KERNEL_REPO = "https://github.com/hairpin01/XKernel"

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
        if not (self._cfg("auto_update_kernel") or self._cfg("update_notifications")):
            return
        task = getattr(self, "_update_task", None)
        if task is None or task.done():
            self._update_task = asyncio.create_task(self._check_kernel_update())

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
        count = len(self._extera_modules_from_config())
        if bool(self._cfg("extera_proxy_all", False)):
            if count:
                return f"Принуждёный для всех, кроме {count} модуля(-лей)"
            return "Принуждёный для всех"
        if count == 0:
            return "Не активированый"
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
                f"{C['injection']} ExteraProxy: <i>{extera_proxy}</i>"
            )
        else:
            text = (
                f"{C['settings']} <b>XPatch Manager</b>\n\n"
                f"{C['lock']} Core: <code>{core_name}</code>\n"
                f"{C['info']} Version XPatchKernel: <code>{xkernel_ver}</code>\n\n"
                f"<blockquote>{C['warning']} <i>XPatchKernel не активен — "
                f"патчи и некоторые функции недоступны</i></blockquote>"
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
            f"Можно выбрать лимит строк и интервал обновления.</blockquote>"
        )
        buttons = [
            [self.Button.inline(f"{self._clear_text(C['logs'])} Live logs", self.on_live_logs_menu, ttl=600)],
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
                )
            ],
            [
                self.Button.inline(
                    f"Auto update: {'ON' if auto_update else 'OFF'}",
                    self.on_toggle_auto_update,
                    ttl=600,
                )
            ],
            [
                self.Button.inline(
                    f"Notify: {'ON' if notifications else 'OFF'}",
                    self.on_toggle_notifications,
                    ttl=600,
                )
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['injection'])} ExteraProxy",
                    self.on_extera_proxy_menu,
                    ttl=600,
                )
            ],
            [
                self.Button.inline(
                    f"{self._clear_text(C['magic'])} Экспериментальные функции",
                    self.on_experimental_settings_menu,
                    ttl=600,
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
        all_enabled = bool(self._cfg("extera_proxy_all", False))
        modules = self._extera_modules_from_config()
        modules_text = ", ".join(html.escape(item) for item in modules) or "нет"
        scopes = self._extera_scopes_from_config()
        root_enabled = "root" in scopes
        scopes_text = "Root" if root_enabled else ", ".join(scope.title() for scope in scopes)
        modules_label = "Исключения" if all_enabled else "Выбранные модули"
        status = html.escape(self._extera_proxy_status_label())
        text = (
            f"{C['injection']} <b>ExteraProxy Inject</b>\n"
            f"<blockquote>{C['info']} Что это? Можно сказать патчит ядро так, что оно <b>даёт Root модулю. Доступ к ядру/клиенту или событию</b>, нужно только если модуль требует защищённый объект (например, session у client)</blockquote>\n"
            f"<blockquote>{C['warning']} Если вы не знаете зачем это вам - <b>не трогайте</b></blockquote>\n"
            f"{C['moon']} Статус: <b>{status}</b>\n"
            f"{C['command']} <b>Scopes:</b> <code>{html.escape(scopes_text)}</code>\n"
            f"{C['info']} {modules_label}: <code>{modules_text}</code>\n"
            f"<blockquote expandable>{C['warning']} <b>Включай только для известных и доверенных модулей. "
            f"Не включай для неизвестных или подозрительных модулей.</b></blockquote>"
        )
        buttons = [
            [
                self.Button.inline(
                    f"Для всех: {'ON' if all_enabled else 'OFF'}",
                    self.on_toggle_extera_proxy_all,
                    ttl=600,
                )
            ],
            (
                [
                    self.Button.inline(
                        "Root: ON → custom",
                        self.on_toggle_extera_scope_root,
                        ttl=600,
                    )
                ]
                if root_enabled
                else [
                    self.Button.inline(
                        f"Kernel: {'ON' if 'kernel' in scopes else 'OFF'}",
                        self.on_toggle_extera_scope_kernel,
                        ttl=600,
                    ),
                    self.Button.inline(
                        f"Client: {'ON' if 'client' in scopes else 'OFF'}",
                        self.on_toggle_extera_scope_client,
                        ttl=600,
                    ),
                    self.Button.inline(
                        f"Event: {'ON' if 'event' in scopes else 'OFF'}",
                        self.on_toggle_extera_scope_event,
                        ttl=600,
                    ),
                ]
            ),
            [
                self.Button.input(
                    f"{self._clear_text(C['+'])} Добавить модуль",
                    self.on_extera_proxy_add_input,
                    placeholder="ModuleName",
                    ttl=600,
                ),
                self.Button.input(
                    "➖ Убрать модуль",
                    self.on_extera_proxy_remove_input,
                    placeholder="ModuleName",
                    ttl=600,
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
                )
            ],
            [
                self.Button.inline(
                    f"Hot reload: {'ON' if hot_reload else 'OFF'}",
                    self.on_toggle_patch_hot_reload,
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

    @callback(ttl=600)
    async def on_experimental_settings_menu(self, call) -> None:
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

    @callback(ttl=600)
    async def on_patches_menu(self, call) -> None:
        C = self.C
        pm = self._get_pm()
        if pm is None:
            await call.answer("XPatchKernel не активен", alert=True)
            return

        lines: list[str] = []

        if pm.applied_patches:
            lines.append(f"<b>{C['true']} Applied ({len(pm.applied_patches)})</b>")
            for (patch_key, target), info in pm.applied_patches.items():
                name = html.escape(info.get("patch", patch_key))
                tgt = html.escape(info.get("target", target))
                lines.append(f"  <code>{name}</code> → <i>{tgt}</i>")

        pending_flat = [
            (pk, t) for pk, targets in pm.pending_patches.items() for t in targets
        ]
        if pending_flat:
            lines.append(f"\n<b>⏳ Pending ({len(pending_flat)})</b>")
            for patch_key, target in pending_flat:
                mod = pm.loaded_patches.get(patch_key)
                try:
                    name = pm._patch_display_name(mod, patch_key) if mod else patch_key
                except Exception:
                    name = patch_key
                lines.append(
                    f"  <code>{html.escape(name)}</code> → <i>{html.escape(target)}</i>"
                )

        if pm.failed_patches:
            lines.append(f"\n<b>{C['off']} Failed ({len(pm.failed_patches)})</b>")
            for (patch_key, target), err in pm.failed_patches.items():
                mod = pm.loaded_patches.get(patch_key)
                try:
                    name = pm._patch_display_name(mod, patch_key) if mod else patch_key
                except Exception:
                    name = patch_key
                short_err = html.escape(str(err)[:60])
                lines.append(f"  <code>{html.escape(name)}</code>: <i>{short_err}</i>")

        body = "\n".join(lines) if lines else "<i>Патчи не найдены</i>"
        text = f"{C['menu']} <b>Патчи</b>\n\n<blockquote expandable>{body}</blockquote>"
        buttons = [
            [self.Button.inline(f"{self._clear_text(C['back'])} Назад", self.on_back_to_main, ttl=600)],
        ]
        await call.edit(text, buttons=buttons)

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
            lines.append(f"\n⏳ Pending ({len(pending)}):")
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
