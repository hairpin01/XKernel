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
        return ("inline", text, callback.__name__)


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
    manager.C = {"utils": "📸", "logs": "📝", "back": "🔙"}
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
