from __future__ import annotations

import asyncio
import hashlib
import sys
import tempfile
import types
from pathlib import Path

import pytest

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
    module_config.DictType = DummyValue
    module_config.Integer = DummyValue
    module_config.ModuleConfig = DummyConfig
    module_config.Placeholders = DummyValue
    module_config.String = DummyValue
    sys.modules["core.lib.loader.module_config"] = module_config

    platform = types.ModuleType("utils.platform")
    platform.get_platform_name = lambda: "test"
    sys.modules["utils.platform"] = platform

    ns: dict[str, object] = {"__name__": "manager_test"}
    exec(
        compile(
            (ROOT / "XPatchKernelManager.py").read_text(encoding="utf-8"),
            "XPatchKernelManager.py",
            "exec",
        ),
        ns,
    )
    return ns["XKernelInstaller"], core


class Button:
    def inline(self, text, callback, **kwargs):
        return ("inline", text, callback.__name__, kwargs.get("data"))

    def input(self, text, callback, **kwargs):
        return ("input", text, callback.__name__, kwargs.get("placeholder"))

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

    def exception(self, *args, **kwargs):
        pass


class Kernel:
    def __init__(self):
        self.saved = []

    async def save_module_config(self, name, cfg):
        self.saved.append((name, cfg))

    def store_module_config_schema(self, name, cfg):
        pass


class StringsStub:
    def __init__(self, data):
        self.data = data["ru"]

    def __call__(self, key, **kwargs):
        value = self.data[key]
        return value.format(**kwargs) if kwargs else value

    def __getitem__(self, key):
        return self.data[key]


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
        "phone": "📱",
        "info": "ℹ️",
        "moon": "🌘",
        "command": "🔨",
        "magic": "🪄",
        "install": "📦",
        "file": "📁",
        "dir": "📂",
        "lock": "🔒",
        "reboot": "🔄",
        "settings": "⚙️",
        "menu": "🔢",
        "+": "➕",
        "reload": "🔁",
        "бууу": "👻",
        "diskette": "💾",
        "catalog": "💻",
        "repo": "🏘",
        "add": "↗️",
        "delete": "❌",
        "rebuild": "🎭",
    }
    manager.Button = Button()
    manager.log = Log()
    manager.kernel = Kernel()
    manager.strings = StringsStub(Manager.strings)
    return manager


class FakeResponse:
    def __init__(self, text: str, status: int = 200):
        self._text = text
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self, encoding="utf-8"):
        return self._text


def test_manager_hash_helpers_accept_common_sha256_formats():
    Manager, _ = load_manager_class()
    digest = "a" * 64

    assert Manager._extract_sha256_hash(digest) == digest
    assert Manager._extract_sha256_hash(f"SHA256:{digest}\n") == digest
    assert Manager._extract_sha256_hash(f"{digest}  XKernel.py\n") == digest

    with pytest.raises(ValueError):
        Manager._extract_sha256_hash("not-a-sha")


def test_manager_download_xkernel_verifies_remote_sha256():
    Manager, _ = load_manager_class()
    source = "print('xkernel')\n"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    requested_urls = []

    class FakeClientSession:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def get(self, url):
            requested_urls.append(url)
            responses = {
                Manager.X_KERNEL_URL: source,
                Manager._hash_url("XKernel"): f"SHA256:{digest}\n",
            }
            return FakeResponse(responses[url])

    aiohttp_stub = sys.modules["aiohttp"]
    aiohttp_stub.ClientTimeout = lambda total: ("timeout", total)
    aiohttp_stub.ClientSession = FakeClientSession

    manager = object.__new__(Manager)

    assert asyncio.run(manager._download_xkernel()) == source
    assert requested_urls == [Manager.X_KERNEL_URL, Manager._hash_url("XKernel")]


def test_manager_download_rejects_sha256_mismatch():
    Manager, _ = load_manager_class()
    source = "print('xkernel')\n"

    class FakeClientSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def get(self, url):
            responses = {
                Manager.X_MANAGER_URL: source,
                Manager._hash_url("XPatchKernelManager"): f"{'0' * 64}\n",
            }
            return FakeResponse(responses[url])

    aiohttp_stub = sys.modules["aiohttp"]
    aiohttp_stub.ClientTimeout = lambda total: ("timeout", total)
    aiohttp_stub.ClientSession = lambda timeout=None: FakeClientSession()

    manager = object.__new__(Manager)

    with pytest.raises(RuntimeError, match="SHA256 mismatch"):
        asyncio.run(manager._download_manager())


def test_repository_hash_files_exist_for_verified_downloads():
    modules = {
        "XKernel": ROOT / "XKernel.py",
        "XPatchKernelManager": ROOT / "XPatchKernelManager.py",
        "__init__": ROOT / "lib/custom/XKernel/__init__.py",
        "mac_types": ROOT / "lib/custom/XKernel/mac_types.py",
        "mac_policy": ROOT / "lib/custom/XKernel/mac_policy.py",
        "mac_context": ROOT / "lib/custom/XKernel/mac_context.py",
        "mac_enforcer": ROOT / "lib/custom/XKernel/mac_enforcer.py",
        "mac_hooks": ROOT / "lib/custom/XKernel/mac_hooks.py",
    }

    for module, source_path in modules.items():
        hash_path = ROOT / "hash" / module / "SHA256:hash.txt"
        expected = hashlib.sha256(
            source_path.read_text(encoding="utf-8").encode("utf-8")
        ).hexdigest()

        assert hash_path.exists(), module
        assert expected in hash_path.read_text(encoding="utf-8"), module


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
            assert "Строк: 5 > 10" in str(buttons)
            assert "Обновление: 10с > 15с" in str(buttons)
            assert "последние <b>5</b>" in text

            call = Call()
            manager._live_logs_event = call
            await manager.on_cycle_live_logs_lines(call)
            assert manager.config["live_logs_max_lines"] == "10"
            assert "Строк: 10 > 20" in str(call.edits[-1][1])

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
        assert "Патчит системные модули MCUB: man и updates." in text
        assert "удаление ядра" in text
        assert "default core" in text
        assert "Удаление XKernel" in str(_)
        assert "Patch system module" in str(_)


def test_system_patch_menus_toggle_runtime_options():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        calls = []

        def set_runtime():
            calls.append(
                {
                    "man_extera": manager.config.data.get("system_patch_man_extera"),
                    "man_mcmac": manager.config.data.get("system_patch_man_mcmac"),
                    "updates_xkernel": manager.config.data.get("system_patch_updates_xkernel"),
                }
            )
            return True

        manager._set_runtime_system_module_patches = set_runtime
        manager._system_module_patch_status = lambda: {"available": True, "options": {}}

        async def run():
            call = Call()
            await manager.on_system_patch_menu(call)
            text, buttons = call.edits[-1]
            assert "Patch system module" in text
            assert "on_system_patch_man_menu" in str(buttons)
            assert "on_system_patch_updates_menu" in str(buttons)

            await manager.on_system_patch_man_menu(call)
            text, buttons = call.edits[-1]
            assert "Patch man" in text
            assert "Man ExteraProxy info: OFF" in str(buttons)
            assert "Man MCMAC info: OFF" in str(buttons)

            await manager.on_toggle_system_patch_man_extera(call)
            assert manager.config["system_patch_man_extera"] is True
            assert calls[-1]["man_extera"] is True

            await manager.on_toggle_system_patch_man_mcmac(call)
            assert manager.config["system_patch_man_mcmac"] is True
            assert calls[-1]["man_mcmac"] is True

            await manager.on_system_patch_updates_menu(call)
            text, buttons = call.edits[-1]
            assert "Patch updates" in text
            assert "Update XKernel status: OFF" in str(buttons)

            await manager.on_toggle_system_patch_updates_xkernel(call)
            assert manager.config["system_patch_updates_xkernel"] is True
            assert calls[-1]["updates_xkernel"] is True

        asyncio.run(run())


def test_settings_and_notify_routes_are_separate():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        manager.config.data.update(
            {
                "stealth_mode": False,
                "auto_update_kernel": False,
                "update_notifications": True,
                "manager_update_notifications": True,
                "update_notification_delay": 0,
            }
        )

        async def run():
            settings_call = Call()
            await manager.on_settings_menu(settings_call)
            assert "<b>XPatch настройки</b>" in settings_call.edits[-1][0]
            assert "Настройки Notify" in str(settings_call.edits[-1][1])

            notify_call = Call()
            await manager.on_notify_settings_menu(notify_call)
            assert "<b>Настройки Notify</b>" in notify_call.edits[-1][0]

            await manager.on_toggle_auto_update(settings_call)
            assert "<b>XPatch настройки</b>" in settings_call.edits[-1][0]

            await manager.on_toggle_notifications(settings_call)
            assert "<b>XPatch настройки</b>" in settings_call.edits[-1][0]

            await manager.on_cycle_notification_delay(notify_call)
            assert "<b>Настройки Notify</b>" in notify_call.edits[-1][0]

            await manager.on_toggle_manager_update_notifications(notify_call)
            assert "<b>Настройки Notify</b>" in notify_call.edits[-1][0]

        asyncio.run(run())


def test_disabled_feature_settings_buttons_are_hidden():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))

        manager.config.data.update({"update_notifications": False})
        _, buttons = manager._build_settings_page()
        rendered = str(buttons)
        assert "Notify: OFF" in rendered
        assert "Настройки Notify" not in rendered

        manager._get_pm = lambda: object()
        manager._client_patch_enabled_db = False
        _, buttons = manager._build_experimental_settings_page()
        rendered = str(buttons)
        assert "Patch: OFF" in rendered
        assert "Client Patch" not in rendered

        manager._client_patch_enabled_db = True
        _, buttons = manager._build_experimental_settings_page()
        rendered = str(buttons)
        assert "Patch: ON" in rendered
        assert "Client Patch" in rendered


def test_hot_reload_settings_menu_is_separate():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        manager._get_pm = lambda: object()

        manager.config.data["experimental_patch_hot_reload"] = False
        _, buttons = manager._build_experimental_settings_page()
        rendered = str(buttons)
        assert "Hot reload: OFF" in rendered
        assert "Настройки Hot reload" not in rendered

        manager.config.data["experimental_patch_hot_reload"] = True
        _, buttons = manager._build_experimental_settings_page()
        rendered = str(buttons)
        assert "Hot reload: ON" in rendered
        assert "Настройки Hot reload" in rendered

        async def run():
            call = Call()
            await manager.on_hot_reload_settings_menu(call)
            text, buttons = call.edits[-1]
            assert "<b>Настройки Hot reload</b>" in text
            assert "если hot reload словил ошибку загрузки" in text
            assert "через сколько секунд пробовать" in text
            assert "подхватывает новые файлы" in text
            assert text.count("<blockquote>") >= 4
            rendered_buttons = str(buttons)
            assert "Умное выключение" in rendered_buttons
            assert "Интервал ожидания" in rendered_buttons
            assert "Отключать при первой ошибке" in rendered_buttons
            assert "Hot load новых патчей" in rendered_buttons

        asyncio.run(run())


def test_hot_reload_settings_hide_smart_retry_when_disable_on_first_fail_enabled():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        manager.config.data.update(
            {
                "experimental_patch_hot_reload": True,
                "experimental_hot_reload_disable_on_first_fail": True,
            }
        )

        text, buttons = manager._build_hot_reload_settings_page()
        rendered_buttons = str(buttons)
        assert "Умное выключение" not in rendered_buttons
        assert "Интервал ожидания" not in rendered_buttons
        assert "если hot reload словил ошибку загрузки" not in text
        assert "через сколько секунд пробовать" not in text
        assert "Отключать при первой ошибке" in rendered_buttons
        assert "Hot load новых патчей" in rendered_buttons


def test_manager_rebuild_replaces_only_exact_name_literals():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        source = (
            'name = "XPatchKernelManager"\n'
            'same = "XPatchKernelManager"\n'
            'long = "XPatchKernelManager update available"\n'
        )

        rebuilt, count = manager._replace_manager_name_literals(
            source,
            old_name="XPatchKernelManager",
            new_name="ForkManager",
        )

        assert count == 2
        assert "ForkManager" in rebuilt
        assert "XPatchKernelManager update available" in rebuilt


def test_manager_rebuild_rejects_invalid_or_non_original_names():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))

        try:
            manager._validate_manager_rebuild_name("bad name!")
        except ValueError:
            pass
        else:
            raise AssertionError("invalid rebuild name was accepted")

        source_path = Path(td) / "XPatchKernelManager.py"
        source_path.write_text('name = "XPatchKernelManager"\n', encoding="utf-8")
        manager._manager_rebuild_source_path = lambda: source_path
        manager.name = "AlreadyForked"

        try:
            manager._build_rebuilt_manager_source("ForkManager")
        except RuntimeError as exc:
            assert "оригинального XPatchKernelManager" in str(exc)
        else:
            raise AssertionError("non-original manager rebuild was accepted")


def test_manager_rebuild_page_and_input_refresh_saved_form():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))

        async def run():
            menu_call = Call()
            await manager.on_manager_rebuild_menu(menu_call)
            assert "Пересборка менеджера" in menu_call.edits[-1][0]
            assert "on_manager_rebuild_name_input" in str(menu_call.edits[-1][1])
            assert "on_manager_rebuild_send" in str(menu_call.edits[-1][1])

            input_event = Call()
            await manager.on_manager_rebuild_name_input(input_event, "ForkManager_1")
            assert manager._manager_rebuild_state()["name"] == "ForkManager_1"
            assert "ForkManager_1" in menu_call.edits[-1][0]
            assert input_event.edits == []

        asyncio.run(run())


def test_manager_rebuild_send_file_and_delete_current():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        manager = make_manager(root)
        manager.config.data["update_notifications"] = False
        source_path = root / "XPatchKernelManager.py"
        source_path.write_text(
            'name = "XPatchKernelManager"\n'
            'strings = {"ru": {"name": "XPatchKernelManager"}}\n'
            'notice = "XPatchKernelManager update available"\n',
            encoding="utf-8",
        )
        manager._manager_rebuild_source_path = lambda: source_path
        manager._manager_rebuild_state().update(
            {"name": "ForkManager_1", "delete_current": True}
        )

        class FakeClient:
            def __init__(self):
                self.sent = []
                self.forwarded = []
                self.deleted = []

            class Message:
                def __init__(self, owner, payload):
                    self.owner = owner
                    self.payload = payload
                    self.id = 123

                async def forward_to(self, chat_id):
                    self.owner.forwarded.append((chat_id, self.payload["file_name"]))

                async def delete(self):
                    self.owner.deleted.append(self.id)

            async def send_file(self, chat_id, file, **kwargs):
                payload = {
                    "chat_id": chat_id,
                    "file_name": Path(file).name,
                    "source": Path(file).read_text(encoding="utf-8"),
                    "kwargs": kwargs,
                }
                self.sent.append(payload)
                return self.Message(self, payload)

        fake_client = FakeClient()
        manager.client = fake_client
        invoked = []

        async def invoke(command, args=None, chat_id=None, reply_to=None):
            invoked.append((command, args, chat_id, reply_to))

        manager.invoke = invoke

        async def run():
            call = Call()
            call.chat_id = 777
            await manager.on_manager_rebuild_send(call)

        asyncio.run(run())

        assert fake_client.sent[0]["chat_id"] == "me"
        assert fake_client.sent[0]["file_name"] == "ForkManager_1.py"
        assert "ForkManager_1" in fake_client.sent[0]["source"]
        assert "XPatchKernelManager update available" in fake_client.sent[0]["source"]
        assert fake_client.forwarded == [(777, "ForkManager_1.py")]
        assert fake_client.deleted == [123]
        assert ("ForkManager_1", manager.config.to_dict()) in manager.kernel.saved
        assert invoked == [("um", "XPatchKernelManager", "me", None)]


def test_manager_rebuild_failed_forward_keeps_current_manager():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        manager = make_manager(root)
        source_path = root / "XPatchKernelManager.py"
        source_path.write_text('name = "XPatchKernelManager"\n', encoding="utf-8")
        manager._manager_rebuild_source_path = lambda: source_path
        manager._manager_rebuild_state().update(
            {"name": "ForkManager_3", "delete_current": True}
        )

        class FakeMessage:
            id = 456

            async def forward_to(self, chat_id):
                raise RuntimeError("bad peer")

            async def delete(self):
                raise AssertionError("saved message must not be deleted")

        class FakeClient:
            def __init__(self):
                self.sent = []

            async def send_file(self, chat_id, file, **kwargs):
                self.sent.append((chat_id, Path(file).name))
                return FakeMessage()

        manager.client = FakeClient()
        invoked = []

        async def invoke(command, args=None, chat_id=None, reply_to=None):
            invoked.append((command, args, chat_id, reply_to))

        manager.invoke = invoke

        async def run():
            call = Call()
            call.chat_id = 777
            await manager.on_manager_rebuild_send(call)
            assert call.answers[-1] == (
                manager.strings("rebuild_saved_only_no_delete"),
                True,
            )

        asyncio.run(run())

        assert manager.client.sent == [("me", "ForkManager_3.py")]
        assert invoked == []


def test_manager_rebuild_skip_config_can_force_wipe_current_config():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        manager = make_manager(root)
        source_path = root / "XPatchKernelManager.py"
        source_path.write_text('name = "XPatchKernelManager"\n', encoding="utf-8")
        manager._manager_rebuild_source_path = lambda: source_path
        manager._manager_rebuild_state().update(
            {
                "name": "ForkManager_2",
                "delete_current": True,
                "copy_config": False,
                "force_wipe_current_config": True,
            }
        )

        class FakeMessage:
            id = 321

            async def forward_to(self, chat_id):
                return None

            async def delete(self):
                return None

        class FakeClient:
            async def send_file(self, *args, **kwargs):
                return FakeMessage()

        manager.client = FakeClient()
        invoked = []

        async def invoke(command, args=None, chat_id=None, reply_to=None):
            invoked.append((command, args, chat_id, reply_to))

        manager.invoke = invoke

        text, buttons = manager._build_manager_rebuild_page()
        assert "Удалить cfg текущего" in text
        assert "on_toggle_manager_rebuild_force_wipe" in str(buttons)

        async def run():
            call = Call()
            call.chat_id = 777
            await manager.on_manager_rebuild_send(call)

        asyncio.run(run())

        assert manager.kernel.saved == []
        assert invoked == [("um", "XPatchKernelManager -f", "me", None)]


def test_update_check_skips_when_xkernel_not_installed():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        manager.config.data.update(
            {"update_notifications": True, "auto_update_kernel": False}
        )
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
        manager.config.data.update(
            {
                "manager_remote_version_cache": "9.9.9",
                "manager_remote_version_checked_at": "9999999999",
            }
        )

        text, _ = manager._build_main_page()

        assert "Надо обновить XPatch Manager из репозитория" in text
        assert "через UI нельзя будет потрогать новые фишки" in text


def test_extera_proxy_page_marks_missing_runtime_as_unsupported():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        manager.config.data.update(
            {
                "extera_proxy_all": False,
                "extera_proxy_modules": "",
                "extera_proxy_scopes": "root",
            }
        )

        text, buttons = manager._build_extera_proxy_page()

        assert "Не поддерживается текущим ядром" in text
        assert "Scopes:</b> <code>Нет доступа</code>" in text
        assert len(buttons) == 1
        assert "Назад" in str(buttons)


def test_extera_proxy_placeholders_mark_missing_runtime_as_unsupported():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        manager.config.data.update(
            {
                "extera_proxy_all": True,
                "extera_proxy_modules": "TrustedMod",
                "extera_proxy_scopes": "root",
            }
        )

        assert manager._extera_proxy_status_label() == "Не поддерживается текущим ядром"
        assert manager._extera_proxy_scopes_label() == "Нет доступа"

        async def run():
            assert (
                await manager._placeholder_extera_proxy_status()
                == "Не поддерживается текущим ядром"
            )
            assert await manager._placeholder_extera_proxy_scopes() == "Нет доступа"

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


def test_extera_proxy_extra_features_open_mcmac_settings():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        manager.config.data.update(
            {
                "extera_proxy_all": False,
                "extera_proxy_modules": "",
                "extera_proxy_scopes": "kernel",
                "mcmac_enabled": False,
                "mcmac_mode": "permissive",
                "mcmac_audit_mode": "all",
                "mcmac_module_types": {},
            }
        )
        manager._get_pm = lambda: object()

        class FakeKernel:
            def __init__(self):
                self.enabled = False
                self.mode = "permissive"
                self.audit_mode = "all"
                self.refreshed = False
                self.contexts = {}

            def mcmac_status(self):
                return {
                    "available": True,
                    "enabled": self.enabled,
                    "mode": self.mode,
                    "audit_mode": self.audit_mode,
                    "audit_allowed": 3,
                    "audit_denied": 2,
                    "audit_blocked": 1,
                    "audit_dropped": 0,
                    "path": "/tmp/core/lib/custom/XKernel",
                    "error": "",
                    "contexts": self.contexts,
                }

            def set_mcmac_enabled(self, enabled):
                self.enabled = bool(enabled)
                return True

            def set_mcmac_mode(self, mode):
                self.mode = str(mode)
                return True

            def set_mcmac_audit_mode(self, audit_mode):
                self.audit_mode = str(audit_mode)
                return True

            def set_mcmac_module_type(self, module_name, security_type):
                self.contexts[str(module_name)] = str(security_type)
                return True

            def clear_mcmac_module_type(self, module_name):
                return self.contexts.pop(str(module_name), None) is not None

            async def refresh_mcmac_runtime(self):
                self.refreshed = True
                return True

        fake_kernel = FakeKernel()
        manager._kernel_object = lambda: fake_kernel

        _, buttons = manager._build_extera_proxy_page()
        assert "Дополнительные возможности" in str(buttons)

        async def run():
            call = Call()
            await manager.on_mcmac_settings_menu(call)
            text, buttons = call.edits[-1]
            assert "<b>MCMAC</b>" in text
            assert "permissive" in text
            assert "Логирование:" in text
            assert "Audit: allowed" in text
            assert "<b>system</b>" in text
            assert "<b>trusted</b>" in text
            assert "<b>standard</b>" in text
            assert "<b>untrusted</b>" in text
            assert "<b>quarantine</b>" in text
            assert "Полный доступ" in text
            assert "subprocess запрещён" in text
            assert "обычные локальные модули" in text
            assert "remote/сомнительные модули" in text
            assert "permissive</b>" in text
            assert "enforcing</b>" in text
            assert "CallInsecure" in text
            assert "Доступен:" not in text
            assert "- ModuleName" not in text
            assert "Download" not in text
            rendered_buttons = str(buttons)
            assert "on_toggle_mcmac_enabled" in rendered_buttons
            assert "on_toggle_mcmac_mode" not in rendered_buttons
            assert "on_mcmac_audit_mode_menu" not in rendered_buttons
            assert "on_mcmac_module_type_input" not in rendered_buttons

            await manager.on_toggle_mcmac_enabled(call)
            assert fake_kernel.enabled is True
            assert manager.config["mcmac_enabled"] is True
            assert "- ModuleName" not in call.edits[-1][0]
            rendered_buttons = str(call.edits[-1][1])
            assert "on_toggle_mcmac_mode" in rendered_buttons
            assert "on_mcmac_audit_mode_menu" in rendered_buttons
            assert "on_mcmac_module_type_input" in rendered_buttons
            assert "on_mcmac_module_type_remove_input" in rendered_buttons

            await manager.on_toggle_mcmac_mode(call)
            assert fake_kernel.mode == "enforcing"
            assert manager.config["mcmac_mode"] == "enforcing"

            await manager.on_mcmac_audit_mode_menu(call)
            text, buttons = call.edits[-1]
            assert "Режим логирования MCMAC" in text
            assert "Все действия" in str(buttons)
            assert "Только запрещённые" in str(buttons)
            assert "Только заблокированные" in str(buttons)
            assert "Выключить audit" in str(buttons)
            assert "on_set_mcmac_audit_mode" in str(buttons)

            await manager.on_set_mcmac_audit_mode(call, "denied")
            assert fake_kernel.audit_mode == "denied"
            assert manager.config["mcmac_audit_mode"] == "denied"
            assert call.answers[-1] == ("MCMAC logging mode: denied", False)
            assert "✅ Только запрещённые" in str(call.edits[-1][1])

            await manager.on_refresh_mcmac_runtime(call)
            assert fake_kernel.refreshed is True

            input_event = Call()
            await manager.on_mcmac_module_type_input(input_event, "UnsafeMod:quarantine")
            assert fake_kernel.contexts["UnsafeMod"] == "quarantine"
            assert manager.config["mcmac_module_types"] == {
                "UnsafeMod": "quarantine"
            }
            await manager.on_mcmac_module_type_input(input_event, "- UnsafeMod")
            assert "UnsafeMod" not in fake_kernel.contexts
            assert manager.config["mcmac_module_types"] == {}

        asyncio.run(run())


def test_mcmac_settings_hides_actions_when_unavailable():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))

        class FakeKernel:
            def mcmac_status(self):
                return {
                    "available": False,
                    "enabled": False,
                    "mode": "permissive",
                    "path": "/tmp/missing",
                    "error": "missing libs",
                    "contexts": {},
                }

        manager._kernel_object = lambda: FakeKernel()
        text, buttons = manager._build_mcmac_settings_page()
        rendered = str(buttons)
        assert "Доступен:" not in text
        assert "MCMAC libs недоступны" in text
        assert "on_toggle_mcmac_enabled" not in rendered
        assert "on_toggle_mcmac_mode" not in rendered
        assert "on_mcmac_module_type_input" not in rendered
        assert "on_refresh_mcmac_runtime" in rendered


def test_patch_detail_page_shows_full_error_and_retries_failed_target():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        manager.C.update(
            {
                "menu": "🔢",
                "true": "✅",
                "off": "❌",
                "info": "ℹ️",
                "pending": "✏️",
                "result": "📤",
                "warning": "⚠️",
                "logs": "📝",
                "on": "✅",
            }
        )

        class PatchModule:
            __xpatch_file__ = "/tmp/patches/FailPatch.py"

        class PatchManager:
            def __init__(self):
                self.loaded_patches = {"patch_failed": PatchModule()}
                self.applied_patches = {}
                self.pending_patches = {}
                self.pending_reasons = {}
                self.failed_patches = {
                    (
                        "patch_failed",
                        "TargetMod",
                    ): "full error text\nwith traceback line",
                }
                self.failed_tracebacks = {
                    (
                        "patch_failed",
                        "TargetMod",
                    ): "Traceback (most recent call last):\nboom",
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
            assert "Повторить" in str(detail_buttons)

            await manager.on_patch_retry(detail_call, detail_data)
            assert pm.retry_targets == [("TargetMod", True)]
            assert "Статус: <b>applied</b>" in detail_call.edits[-1][0]
            assert "retried" in detail_call.edits[-1][0]

        asyncio.run(run())


def test_patch_detail_load_failure_uses_problem_patch_label():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        manager.C.update(
            {
                "menu": "🔢",
                "true": "✅",
                "off": "❌",
                "info": "ℹ️",
                "pending": "✏️",
                "result": "📤",
                "warning": "⚠️",
                "logs": "📝",
                "on": "✅",
            }
        )

        class PatchManager:
            loaded_patches = {}
            applied_patches = {}
            pending_patches = {}
            pending_reasons = {}
            failed_patches = {("patch_bad", "<load>"): "SyntaxError"}
            failed_tracebacks = {("patch_bad", "<load>"): "Traceback..."}
            disabled_patches = set()

            @staticmethod
            def _normalize(value):
                return str(value).strip().casefold()

            @staticmethod
            def _patch_display_name(module, fallback):
                return "BadPatch"

            def is_patch_disabled(self, patch_key):
                return False

            async def reload_patch_key(self, patch_key):
                return {"reloaded": [patch_key], "failed": [], "missing": []}

        manager._get_pm = lambda: PatchManager()

        async def run():
            call = Call()
            data = {"patch_key": "patch_bad", "target": "<load>", "status": "failed"}
            await manager.on_patch_detail(call, data)
            text, buttons = call.edits[-1]
            assert "SyntaxError" in text
            assert "Загрузить проблемный патч" in str(buttons)

        asyncio.run(run())


def test_patch_detail_actions_and_version_compatibility():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        manager.C.update(
            {
                "menu": "🔢",
                "true": "✅",
                "off": "❌",
                "info": "ℹ️",
                "pending": "✏️",
                "result": "📤",
                "warning": "⚠️",
                "logs": "📝",
                "on": "✅",
            }
        )

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
        detail_data = {
            "patch_key": "patch_compat",
            "target": "TargetMod",
            "status": "applied",
        }

        async def run():
            detail_call = Call()
            await manager.on_patch_detail(detail_call, detail_data)
            text, buttons = detail_call.edits[-1]
            assert "Патч совместим с текущей версией XKernel" in text
            assert "Перезагрузить патч" in str(buttons)
            assert "Откатить применение" in str(buttons)
            assert "Отключить патч" in str(buttons)

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
        manager.C.update(
            {
                "menu": "🔢",
                "true": "✅",
                "off": "❌",
                "info": "ℹ️",
                "pending": "✏️",
                "result": "📤",
                "warning": "⚠️",
                "logs": "📝",
                "on": "✅",
            }
        )

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
        info = manager._patch_detail_info(
            pm, {"patch_key": "patch_future", "target": "TargetMod"}
        )
        text = manager._patch_detail_text(info)
        assert "Минимальная версия XKernel для этого патча: 9.0.0" in text


def test_patch_detail_warns_when_required_xkernel_missing():
    with tempfile.TemporaryDirectory() as td:
        manager = make_manager(Path(td))
        manager.C.update(
            {
                "menu": "🔢",
                "true": "✅",
                "off": "❌",
                "info": "ℹ️",
                "pending": "✏️",
                "result": "📤",
                "warning": "⚠️",
                "logs": "📝",
                "on": "✅",
            }
        )

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
            assert "Default > standard: ON" in str(buttons)

            await manager.on_toggle_remove_option(call, "backups")
            await manager.on_toggle_remove_option(call, "patches")
            await manager.on_toggle_remove_option(call, "manager")
            await manager.on_remove_xkernel_start(call)

            assert not xkernel.exists()
            assert not (xkernel.parent / "XKernel.py.bak-1").exists()
            assert not patches.exists()
            assert (root / "core" / ".default_core").read_text(
                encoding="utf-8"
            ) == "standard\n"
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
            assert (root / "core" / ".default_core").read_text(
                encoding="utf-8"
            ) == "XKernel\n"
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
