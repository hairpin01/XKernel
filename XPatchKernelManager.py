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
    version = "1.2.0"
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
        self._ensure_update_task()
        self.log.info("XKernelInstaller loaded")

    async def on_unload(self) -> None:
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

    def _kernel_attr(
        self,
        name: str,
        default: Any = None,
        *,
        protected: bool = False,
    ) -> Any:
        if protected:
            try:
                return object.__getattribute__(self.kernel, name)
            except Exception:
                pass
        try:
            return getattr(self.kernel, name, default)
        except Exception:
            return default

    def _kernel_patch_manager(self) -> Any | None:
        try:
            return object.__getattribute__(self.kernel, "patch_manager")
        except Exception:
            return None

    def _apply_stealth_from_config(self) -> None:
        if not self._cfg("stealth_mode", False):
            return

        try:
            enable_stealth = object.__getattribute__(self.kernel, "enable_stealth_mode")
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
            disable_stealth = object.__getattribute__(self.kernel, "disable_stealth_mode")
        except Exception:
            disable_stealth = None
        if callable(disable_stealth):
            disable_stealth()

    def _clear_text(self, text) -> str:
        return  re.sub(r"<[^>]+>", "", text)

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

        if is_xpatch:
            text = (
                f"{C['settings']} <b>XPatch Manager</b>\n\n"
                f"{C['true']} <b>XPatchKernel</b> <code>{ver}</code>\n"
                f"{C['info']} Version XPatchKernel: <code>{xkernel_ver}</code>\n"
                f"{C['menu']} Applied: <b>{applied}</b>  "
                f"Pending: <b>{pending}</b>  "
                f"Failed: <b>{failed}</b>\n"
                f"{C['lock']} Stealth: <code>{stealth}</code>  "
                f"Auto update: <code>{auto_update}</code>  "
                f"Notify: <code>{notifications}</code>"
            )
        else:
            text = (
                f"{C['settings']} <b>XPatch Manager</b>\n\n"
                f"{C['lock']} Core: <code>{core_name}</code>\n"
                f"{C['info']} Version XPatchKernel: <code>{xkernel_ver}</code>\n\n"
                f"{C['warning']} <i>XPatchKernel не активен — "
                f"патчи и некоторые функции недоступны</i>"
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
                        f"❌ {failed} failed", self.on_patches_menu, ttl=600
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
                self.Button.inline("🔄 Check update", self.on_check_update, ttl=300),
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
        text, buttons = self._build_main_page()
        await call.edit(text, buttons=buttons)

    def _build_settings_page(self) -> tuple[str, list]:
        C = self.C
        stealth = bool(self._cfg("stealth_mode", False))
        auto_update = bool(self._cfg("auto_update_kernel", False))
        notifications = bool(self._cfg("update_notifications", True))
        text = (
            f"{C['settings']} <b>XPatch настройки</b>\n\n"
            f"{self._bool_icon(stealth)} <b>Stealth mode</b>\n"
            f"  <i>VERSION без .XPatch, без VERSION_XKERNEL/ver, CORE_NAME=standard</i>\n\n"
            f"{self._bool_icon(auto_update)} <b>Auto update ядра</b>\n"
            f"  <i>Если VERSION_XKERNEL стал выше — ставить сразу</i>\n\n"
            f"{self._bool_icon(notifications)} <b>Уведомления об обновлении</b>\n"
            f"  <i>Бот пишет в лог-чат или в ЛС клиенту</i>"
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
            [self.Button.inline(f"{self._clear_text(C['back'])} Назад", self.on_back_to_main, ttl=600)],
        ]
        return text, buttons

    @staticmethod
    def _bool_icon(value: bool) -> str:
        return "✅" if value else "⬜"

    @callback(ttl=600)
    async def on_settings_menu(self, call) -> None:
        text, buttons = self._build_settings_page()
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

    @callback(ttl=600)
    async def on_patches_menu(self, call) -> None:
        C = self.C
        pm = self._get_pm()
        if pm is None:
            await call.answer("XPatchKernel не активен", alert=True)
            return

        lines: list[str] = []

        if pm.applied_patches:
            lines.append(f"<b>{self._clear_text(C['true'])} Applied ({len(pm.applied_patches)})</b>")
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
            lines.append(f"\n<b>❌ Failed ({len(pm.failed_patches)})</b>")
            for (patch_key, target), err in pm.failed_patches.items():
                mod = pm.loaded_patches.get(patch_key)
                try:
                    name = pm._patch_display_name(mod, patch_key) if mod else patch_key
                except Exception:
                    name = patch_key
                short_err = html.escape(str(err)[:60])
                lines.append(f"  <code>{html.escape(name)}</code>: <i>{short_err}</i>")

        body = "\n".join(lines) if lines else "<i>Патчи не найдены</i>"
        text = f"{C['menu']} <b>Патчи</b>\n\n{body}"
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
            f"🖥 Platform: <code>{html.escape(get_platform_name())}</code>",
        ]

        text = f"{C['info']} <b>XKernel · Подробно</b>\n\n" + "\n".join(lines)
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
                f"{C['file']} Файл: <code>{html.escape(str(target_path))}</code>\n"
                f"{C['lock']} SHA: <code>{sha[:16]}…</code>\n\n"
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
                "✅ <b>XKernel уже актуален</b>\n\n"
                f"Local: <code>{self._format_version(update['local_version'])}</code>\n"
                f"Remote: <code>{self._format_version(update['remote_version'])}</code>",
                buttons=[[self.Button.inline(f"{self._clear_text(self.C['back'])} Назад", self.on_back_to_main, ttl=600)]],
            )
            return

        await call.edit(
            "🔄 <b>Доступно обновление XKernel</b>\n\n"
            f"Local: <code>{self._format_version(update['local_version'])}</code>\n"
            f"Remote: <code>{self._format_version(update['remote_version'])}</code>",
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
            f"Version: <code>{self._format_version(remote_version)}</code>\n"
            f"{C['file']} Файл: <code>{html.escape(str(target_path))}</code>\n"
            f"{C['lock']} SHA: <code>{sha[:16]}…</code>\n\n"
            f"{C['warning']} <i>Нужен рестарт MCUB</i>\n"
            f"Открой менеджер заново: <code>.xm</code>",
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
            lines.append(f"\n❌ Failed ({len(failed)}):")
            for name, tgt in failed:
                lines.append(
                    f"  <code>{html.escape(name)}</code> → <i>{html.escape(tgt)}</i>"
                )
        if skipped:
            lines.append(f"\n⏭ Skipped: {len(skipped)}")

        needs_restart = bool(applied)
        if needs_restart:
            lines.append(f"\n{C['warning']} <i>Нужен рестарт для применения патчей</i>")

        text = "\n".join(lines)
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
            f"<code>{html.escape(str(latest))}</code>\n\n"
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
            f"Восстановлен: <code>{html.escape(str(latest_backup))}</code>\n\n"
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
                f"{C['file']} Файл: <code>{html.escape(str(target_path))}</code>\n"
                f"{C['lock']} SHA: <code>{sha[:16]}…</code>\n"
                f"<blockquote>Default core: "
                f"<code>{'XKernel' if default_changed else 'не менял'}</code></blockquote>\n\n"
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
            await self._edit(event, "<b>Backup для XKernel не найден</b>")
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
            f"{C['true']} <b>XKernel rollback выполнен</b>\n"
            f"Восстановлен: <code>{html.escape(str(latest_backup))}</code>\n"
            f"<blockquote>{C['warning']} Ребутни MCUB</blockquote>",
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
            "🔄 <b>Доступно обновление XKernel</b>\n\n"
            f"Local: <code>{self._format_version(update['local_version'])}</code>\n"
            f"Remote: <code>{self._format_version(remote_version)}</code>",
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
