from __future__ import annotations

import asyncio
import sys
import tempfile
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DummyBase:
    pass


class DummyConfig:
    def __init__(self, *args, **kwargs):
        self.data = {}

    def to_dict(self):
        return dict(self.data)

    def from_dict(self, data):
        self.data.update(data)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def __setitem__(self, key, value):
        self.data[key] = value

    def __getitem__(self, key):
        return self.data[key]


class DummyValue:
    def __init__(self, *args, **kwargs):
        pass


def identity_decorator(*args, **kwargs):
    def deco(fn):
        return fn

    return deco


def load_manager_class():
    utils = types.ModuleType("utils")
    utils.register_decorated_placeholders = lambda *a, **kw: None
    utils.unregister_scope = lambda *a, **kw: None
    utils.format_placeholders = lambda *a, **kw: ""
    utils.resolve_placeholders = lambda *a, **kw: ""
    utils.placeholders = identity_decorator
    sys.modules["utils"] = utils
    sys.modules["aiohttp"] = types.ModuleType("aiohttp")
    core = types.ModuleType("core")
    sys.modules["core"] = core
    sys.modules["core.lib"] = types.ModuleType("core.lib")
    sys.modules["core.lib.loader"] = types.ModuleType("core.lib.loader")

    module_base = types.ModuleType("core.lib.loader.module_base")
    module_base.ModuleBase = DummyBase
    module_base.callback = identity_decorator
    module_base.command = identity_decorator
    sys.modules["core.lib.loader.module_base"] = module_base

    module_config = types.ModuleType("core.lib.loader.module_config")
    module_config.Boolean = DummyValue
    module_config.ConfigValue = DummyValue
    module_config.ModuleConfig = DummyConfig
    module_config.Placeholders = DummyValue
    module_config.String = DummyValue
    sys.modules["core.lib.loader.module_config"] = module_config

    platform = types.ModuleType("utils.platform")
    platform.get_platform_name = lambda: "test"
    sys.modules["utils.platform"] = platform

    ns: dict[str, object] = {"__name__": "manager_test"}
    exec(compile((ROOT / "XPatchKernelManager.py").read_text(encoding="utf-8"), "XPatchKernelManager.py", "exec"), ns)
    return ns["XKernelInstaller"], core


class Button:
    def inline(self, text, callback, **kwargs):
        return ("inline", text, callback.__name__, kwargs.get("data"))

    def url(self, text, url, **kwargs):
        return ("url", text, url)


class Call:
    def __init__(self):
        self.edits = []
        self.answers = []

    async def edit(self, text, buttons=None):
        self.edits.append((text, buttons))

    async def answer(self, text, alert=False):
        self.answers.append((text, alert))


class Log:
    def debug(self, *args, **kwargs):
        pass


class Kernel:
    def __init__(self):
        self.saved = []

    async def save_module_config(self, name, cfg):
        self.saved.append((name, cfg))

    def store_module_config_schema(self, name, cfg):
        pass


def make_manager(tmp_root: Path):
    Manager, core = load_manager_class()
    (tmp_root / "core").mkdir()
    (tmp_root / "logs").mkdir()
    core.__file__ = str(tmp_root / "core" / "__init__.py")

    manager = object.__new__(Manager)
    manager.name = "XPatchKernelManager"
    manager.config = DummyConfig()
    manager.config.data = {
        "live_logs_max_lines": "5",
        "live_logs_refresh_interval": "10",
    }
    manager.C = {
        "utils": "📸",
        "logs": "📝",
        "back": "🔙",
        "pending": "✏️",
        "result": "📤",
        "warning": "⚠️",
        "on": "✅",
        "true": "✅",
        "off": "❌",
        "injection": "🧬",
        "info": "ℹ️",
        "moon": "🌘",
        "command": "🔨",
        "magic": "🪄",
        "install": "📦",
        "file": "📁",
        "lock": "🔒",
        "reboot": "🔄",
        "settings": "⚙️",
        "menu": "🔢",
        "+": "➕",
        "reload": "🔁",
    }
    manager.Button = Button()
    manager.log = Log()
    manager.kernel = Kernel()
    return manager


def test_live_logs_cycle_buttons_update_config_and_form():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        manager = make_manager(root)
        (root / "logs" / "kernel.log").write_text(
            "\n".join(f"[xpatch] line{i}" for i in range(30)),
            encoding="utf-8",
        )

        async def run():
            text, buttons = await manager._build_live_logs_page()
            assert "Строк: 5 → 10" in str(buttons)
            assert "Обновление: 10с → 15с" in str(buttons)
            assert "последние <b>5</b>" in text

            call = Call()
            manager._live_logs_event = call
            await manager.on_cycle_live_logs_lines(call)
            assert manager.config["live_logs_max_lines"] == "10"
            assert "Строк: 10 → 20" in str(call.edits[-1][1])

            await manager.on_cycle_live_logs_interval(call)
            assert manager.config["live_logs_refresh_interval"] == "15"
            assert "Обновление: <b>15</b>" in call.edits[-1][0]

        asyncio.run(run())


def test_utils_page_describes_live_logs():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        text, _ = manager._build_utils_page()
        assert "<blockquote>" in text
        assert "Live logs" in text
        assert "Можно выбрать лимит строк" in text
        assert "мастер удаления ядра" in text
        assert "default core" in text
        assert "Удаление XKernel" in str(_)


def test_update_check_skips_when_xkernel_not_installed():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        manager.config.data.update({"update_notifications": True, "auto_update_kernel": False})
        calls = {"download": 0, "notice": 0}

        async def download():
            calls["download"] += 1
            return ""

        async def notice(*args, **kwargs):
            calls["notice"] += 1

        manager._download_xkernel = download
        manager._send_update_notice = notice

        asyncio.run(manager._check_kernel_update())

        assert calls == {"download": 0, "notice": 0}


def test_manager_remote_version_cache_is_refreshed_without_spamming_github():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        calls = {"download": 0}

        async def download_manager():
            calls["download"] += 1
            return 'class XKernelInstaller:\n    version = "9.9.9"\n'

        manager._download_manager = download_manager

        async def run():
            remote = await manager._refresh_manager_update_cache(force=True)
            assert remote == (9, 9, 9)
            assert manager.config["manager_remote_version_cache"] == "9.9.9"
            assert calls["download"] == 1

            cached = await manager._refresh_manager_update_cache()
            assert cached == (9, 9, 9)
            assert calls["download"] == 1

        asyncio.run(run())


def test_main_page_warns_when_cached_manager_version_is_newer():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        manager.config.data.update({
            "manager_remote_version_cache": "9.9.9",
            "manager_remote_version_checked_at": "9999999999",
        })

        text, _ = manager._build_main_page()

        assert "Надо обновить XPatch Manager из репозитория" in text
        assert "через UI нельзя будет потрогать новые фишки" in text


def test_extera_proxy_page_marks_missing_runtime_as_unsupported():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        manager.config.data.update({
            "extera_proxy_all": False,
            "extera_proxy_modules": "",
            "extera_proxy_scopes": "root",
        })

        text, buttons = manager._build_extera_proxy_page()

        assert "Не поддерживается текущим ядром" in text
        assert "Scopes:</b> <code>No access</code>" in text
        assert len(buttons) == 1
        assert "Назад" in str(buttons)


def test_extera_proxy_placeholders_mark_missing_runtime_as_unsupported():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        manager.config.data.update({
            "extera_proxy_all": True,
            "extera_proxy_modules": "TrustedMod",
            "extera_proxy_scopes": "root",
        })

        assert manager._extera_proxy_status_label() == "Не поддерживается текущим ядром"
        assert manager._extera_proxy_scopes_label() == "No access"

        async def run():
            assert await manager._placeholder_extera_proxy_status() == "Не поддерживается текущим ядром"
            assert await manager._placeholder_extera_proxy_scopes() == "No access"

        asyncio.run(run())


def test_experimental_menu_is_blocked_without_xkernel_runtime():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))

        async def run():
            call = Call()
            await manager.on_experimental_settings_menu(call)
            assert call.answers == [("Не поддерживается текущим ядром", True)]
            assert "Экспериментальные функции недоступны" in call.edits[-1][0]

        asyncio.run(run())


def test_patch_detail_page_shows_full_error_and_retries_failed_target():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        manager.C.update({"menu": "🔢", "true": "✅", "off": "❌", "info": "ℹ️", "pending": "✏️", "result": "📤", "warning": "⚠️", "logs": "📝", "on": "✅"})

        class PatchModule:
            __xpatch_file__ = "/tmp/patches/FailPatch.py"

        class PatchManager:
            def __init__(self):
                self.loaded_patches = {"patch_failed": PatchModule()}
                self.applied_patches = {}
                self.pending_patches = {}
                self.pending_reasons = {}
                self.failed_patches = {
                    ("patch_failed", "TargetMod"): "full error text\nwith traceback line",
                }
                self.failed_tracebacks = {
                    ("patch_failed", "TargetMod"): "Traceback (most recent call last):\nboom",
                }
                self.retry_targets = []

            @staticmethod
            def _normalize(value):
                return str(value).strip().casefold()

            @staticmethod
            def _patch_display_name(module, fallback):
                return "FailPatch"

            async def apply_for_target(self, target, force=True):
                self.retry_targets.append((target, force))
                self.failed_patches.clear()
                norm = self._normalize(target)
                self.applied_patches[("patch_failed", norm)] = {
                    "patch": "FailPatch",
                    "target": target,
                    "result": "retried",
                }
                return {"applied": [("FailPatch", target)]}

        pm = PatchManager()
        manager._get_pm = lambda: pm

        async def run():
            menu_call = Call()
            await manager.on_patches_menu(menu_call)
            assert "Failed: <b>1</b>" in menu_call.edits[-1][0]
            detail_data = menu_call.edits[-1][1][0][0][3]
            assert detail_data == {
                "patch_key": "patch_failed",
                "target": "TargetMod",
                "status": "failed",
            }

            detail_call = Call()
            await manager.on_patch_detail(detail_call, detail_data)
            detail_text, detail_buttons = detail_call.edits[-1]
            assert "full error text" in detail_text
            assert "with traceback line" in detail_text
            assert "Traceback (most recent call last)" in detail_text
            assert "Retry" in str(detail_buttons)

            await manager.on_patch_retry(detail_call, detail_data)
            assert pm.retry_targets == [("TargetMod", True)]
            assert "Status: <b>applied</b>" in detail_call.edits[-1][0]
            assert "retried" in detail_call.edits[-1][0]

        asyncio.run(run())


def test_patch_detail_actions_and_version_compatibility():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        manager.C.update({"menu": "🔢", "true": "✅", "off": "❌", "info": "ℹ️", "pending": "✏️", "result": "📤", "warning": "⚠️", "logs": "📝", "on": "✅"})

        class PatchModule:
            __xpatch_file__ = "/tmp/patches/CompatPatch.py"
            PATCH_REQUIRES_XKERNEL = (0, 0, 6)

            @staticmethod
            def unapply_patch(kernel, target):
                return "ok"

        class PatchManager:
            def __init__(self):
                self.loaded_patches = {"patch_compat": PatchModule()}
                self.applied_patches = {
                    ("patch_compat", "targetmod"): {
                        "patch": "CompatPatch",
                        "target": "TargetMod",
                        "result": "ok",
                    }
                }
                self.pending_patches = {}
                self.pending_reasons = {}
                self.failed_patches = {}
                self.failed_tracebacks = {}
                self.disabled_patches = set()
                self.reload_calls = []
                self.unapply_calls = []
                self.disabled_calls = []

            @staticmethod
            def _normalize(value):
                return str(value).strip().casefold()

            @staticmethod
            def _patch_display_name(module, fallback):
                return "CompatPatch"

            @staticmethod
            def _patch_targets(module):
                return ["TargetMod"]

            @staticmethod
            def _unapply_callback(module):
                return module.unapply_patch

            @staticmethod
            def _patch_required_xkernel(module):
                return module.PATCH_REQUIRES_XKERNEL

            @staticmethod
            def _current_xkernel_version():
                return (0, 0, 6)

            @staticmethod
            def _version_less(current, required):
                return current < required

            @staticmethod
            def _format_version(version):
                return ".".join(str(part) for part in version)

            def is_patch_disabled(self, patch_key):
                return patch_key in self.disabled_patches

            def set_patch_disabled(self, patch_key, disabled=True):
                self.disabled_calls.append((patch_key, disabled))
                if disabled:
                    self.disabled_patches.add(patch_key)
                else:
                    self.disabled_patches.discard(patch_key)

            async def reload_patch_key(self, patch_key):
                self.reload_calls.append(patch_key)
                return {"reloaded": [patch_key], "failed": [], "missing": []}

            async def unapply_patch(self, patch_key, target):
                self.unapply_calls.append((patch_key, target))
                self.applied_patches.clear()
                return "unapplied"

            async def unapply_patch_key(self, patch_key):
                self.unapply_calls.append((patch_key, "<all>"))
                self.applied_patches.clear()
                return {"unapplied": [("CompatPatch", "TargetMod")]}

            async def apply_all(self, force=False):
                self.applied_patches[("patch_compat", "targetmod")] = {
                    "patch": "CompatPatch",
                    "target": "TargetMod",
                    "result": "enabled",
                }
                return {"applied": [("CompatPatch", "TargetMod")]}

        pm = PatchManager()
        manager._get_pm = lambda: pm
        detail_data = {"patch_key": "patch_compat", "target": "TargetMod", "status": "applied"}

        async def run():
            detail_call = Call()
            await manager.on_patch_detail(detail_call, detail_data)
            text, buttons = detail_call.edits[-1]
            assert "Патч совместим с текущей версией XKernel" in text
            assert "Reload patch" in str(buttons)
            assert "Unapply" in str(buttons)
            assert "Disable patch" in str(buttons)

            await manager.on_patch_reload(detail_call, detail_data)
            assert pm.reload_calls == ["patch_compat"]

            await manager.on_patch_unapply(detail_call, detail_data)
            assert ("patch_compat", "TargetMod") in pm.unapply_calls

            await manager.on_patch_disable(detail_call, detail_data)
            assert ("patch_compat", True) in pm.disabled_calls
            assert ("patch_compat", "<all>") in pm.unapply_calls

            await manager.on_patch_enable(detail_call, detail_data)
            assert ("patch_compat", False) in pm.disabled_calls
            assert "enabled" in detail_call.edits[-1][0]

        asyncio.run(run())


def test_patch_detail_warns_about_required_xkernel_version():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        manager.C.update({"menu": "🔢", "true": "✅", "off": "❌", "info": "ℹ️", "pending": "✏️", "result": "📤", "warning": "⚠️", "logs": "📝", "on": "✅"})

        class PatchModule:
            __xpatch_file__ = "/tmp/patches/FuturePatch.py"
            PATCH_REQUIRES_XKERNEL = (9, 0, 0)

        class PatchManager:
            loaded_patches = {"patch_future": PatchModule()}
            applied_patches = {}
            pending_patches = {"patch_future": ["TargetMod"]}
            pending_reasons = {("patch_future", "targetmod"): "waiting"}
            failed_patches = {}
            disabled_patches = set()

            @staticmethod
            def _normalize(value):
                return str(value).strip().casefold()

            @staticmethod
            def _patch_display_name(module, fallback):
                return "FuturePatch"

            @staticmethod
            def _unapply_callback(module):
                return None

            @staticmethod
            def _patch_required_xkernel(module):
                return module.PATCH_REQUIRES_XKERNEL

            @staticmethod
            def _current_xkernel_version():
                return (0, 0, 6)

            @staticmethod
            def _version_less(current, required):
                return current < required

            @staticmethod
            def _format_version(version):
                return ".".join(str(part) for part in version)

            @staticmethod
            def is_patch_disabled(patch_key):
                return False

        pm = PatchManager()
        info = manager._patch_detail_info(pm, {"patch_key": "patch_future", "target": "TargetMod"})
        text = manager._patch_detail_text(info)
        assert "Минимальная версия XKernel для этого патча: 9.0.0" in text


def test_patch_detail_warns_when_required_xkernel_missing():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        manager.C.update({"menu": "🔢", "true": "✅", "off": "❌", "info": "ℹ️", "pending": "✏️", "result": "📤", "warning": "⚠️", "logs": "📝", "on": "✅"})

        info = {
            "patch_key": "patch_plain",
            "name": "PlainPatch",
            "target": "TargetMod",
            "file": "/tmp/PlainPatch.py",
            "status": "loaded",
            "result": "",
            "error": "",
            "pending_reason": "",
            "traceback": "",
            "version_known": False,
            "version_ok": True,
        }
        text = manager._patch_detail_text(info)
        assert "Минимальная версия XKernel для этого патча не указана" in text


def test_remove_xkernel_page_toggles_and_executes_selected_actions():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        manager = make_manager(root)
        manager.C.update({"true": "✅", "off": "❌", "warning": "⚠️", "back": "🔙"})

        xkernel = root / "core" / "kernel" / "XKernel.py"
        xkernel.parent.mkdir(parents=True, exist_ok=True)
        xkernel.write_text("Kernel = XPatchKernel\n", encoding="utf-8")
        (xkernel.parent / "XKernel.py.bak-1").write_text("backup", encoding="utf-8")
        patches = root / "patches"
        patches.mkdir()
        (patches / "Patch.py").write_text("PATCH_TARGET='A'\n", encoding="utf-8")

        calls = []

        async def invoke(command, **kwargs):
            calls.append((command, kwargs))

        manager.invoke = invoke

        async def run():
            call = Call()
            await manager.on_remove_xkernel_menu(call)
            text, buttons = call.edits[-1]
            assert "Удаление XKernel" in text
            assert "Ядро: ON" in str(buttons)
            assert "Все бекапы: OFF" in str(buttons)
            assert "Default → standard: ON" in str(buttons)

            await manager.on_toggle_remove_option(call, "backups")
            await manager.on_toggle_remove_option(call, "patches")
            await manager.on_toggle_remove_option(call, "manager")
            await manager.on_remove_xkernel_start(call)

            assert not xkernel.exists()
            assert not (xkernel.parent / "XKernel.py.bak-1").exists()
            assert not patches.exists()
            assert (root / "core" / ".default_core").read_text(encoding="utf-8") == "standard\n"
            assert calls == [
                ("um", {"args": "XPatchKernelManager", "chat_id": "me"}),
                ("restart", {"chat_id": "me"}),
            ]
            assert "Удаление XKernel завершено" in call.edits[-1][0]

        asyncio.run(run())


def test_inline_install_asks_whether_to_set_default_core():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        manager = make_manager(root)
        source = """
from .standard import Kernel as KernelBase

class XPatchPatchManager:
    pass

class XPatchKernel(KernelBase):
    pass

VERSION_XKERNEL = (0, 0, 6)
Kernel = XPatchKernel
"""

        async def download():
            return source

        manager._download_xkernel = download

        async def run():
            call = Call()
            await manager.on_install_start(call)
            text, buttons = call.edits[-1]
            assert "Сделать XKernel ядром по умолчанию" in text
            assert "Установить по дефолту" in str(buttons)
            assert "Нет, спасибо" in str(buttons)
            assert (root / "core" / "kernel" / "XKernel.py").exists()

            await manager.on_install_set_default(call)
            assert (root / "core" / ".default_core").read_text(encoding="utf-8") == "XKernel\n"
            assert call.answers[-1] == ("XKernel установлен по умолчанию", False)
            assert "Default core: <code>XKernel</code>" in call.edits[-1][0]

        asyncio.run(run())


def test_inline_install_can_skip_default_core_change():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))

        async def run():
            call = Call()
            await manager.on_install_skip_default(call)
            assert call.answers[-1] == ("Default core не менял", False)
            assert "Default core: <code>не менял</code>" in call.edits[-1][0]

        asyncio.run(run())
