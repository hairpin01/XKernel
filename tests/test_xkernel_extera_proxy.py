from __future__ import annotations

import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_xkernel_with_proxy_stubs():
    core = types.ModuleType("core")
    lib = types.ModuleType("core.lib")
    loader = types.ModuleType("core.lib.loader")
    kernel_proxy = types.ModuleType("core.lib.loader.kernel_proxy")

    class ModuleKernelProxy:
        def __init__(self, kernel=None, module_name="test"):
            self._kernel = kernel
            self._module_name = module_name

        def __getattribute__(self, name):
            if name in {"_kernel", "_module_name", "__class__"}:
                return object.__getattribute__(self, name)
            protected = getattr(kernel_proxy, "PROTECTED_KERNEL_NAMES", frozenset())
            if name in protected or name.startswith("_"):
                raise RuntimeError(f"protected: {name}")
            return getattr(object.__getattribute__(self, "_kernel"), name)

    class ClientProxy:
        def __init__(self, client, module_name):
            self.client = client
            self.module_name = module_name

    class EventProxy:
        pass

    def original_get_module_kernel(kernel, module_name, is_system):
        return kernel if is_system else ModuleKernelProxy(kernel, module_name)

    def original_get_module_client(kernel, module_name, is_system):
        return kernel.client if is_system else ClientProxy(kernel.client, module_name)

    def original_wrap_event_for_module(event, module_name, kernel):
        return EventProxy()

    kernel_proxy.PROTECTED_KERNEL_NAMES = frozenset()
    kernel_proxy.ModuleKernelProxy = ModuleKernelProxy
    kernel_proxy.ClientProxy = ClientProxy
    kernel_proxy.EventProxy = EventProxy
    kernel_proxy.get_module_kernel = original_get_module_kernel
    kernel_proxy.get_module_client = original_get_module_client
    kernel_proxy.wrap_event_for_module = original_wrap_event_for_module

    sys.modules["core"] = core
    sys.modules["core.lib"] = lib
    sys.modules["core.lib.loader"] = loader
    sys.modules["core.lib.loader.kernel_proxy"] = kernel_proxy
    loader.kernel_proxy = kernel_proxy

    # Simulate modules that imported proxy helpers directly before XKernel hooks.
    runtime = types.ModuleType("core.lib.loader.hikka_compat.runtime")
    runtime.ClientProxy = ClientProxy
    base = types.ModuleType("core.lib.loader.base")
    base.get_module_client = original_get_module_client
    base.wrap_event_for_module = original_wrap_event_for_module
    user_loader = types.ModuleType("core.lib.mixin.user_loader_mixin")
    user_loader.get_module_client = original_get_module_client
    user_loader.get_module_kernel = original_get_module_kernel
    sys.modules[runtime.__name__] = runtime
    sys.modules[base.__name__] = base
    sys.modules[user_loader.__name__] = user_loader

    source = (ROOT / "XKernel.py").read_text(encoding="utf-8").replace(
        "from .standard import Kernel as KernelBase",
        "class KernelBase:\n"
        "    def __init__(self):\n"
        "        self.VERSION = '1.2.3'\n"
        "        self._loader = None\n"
        "        self.loaded_modules = {}\n"
        "        self.system_modules = {}\n"
        "        self.logger = None\n"
        "        self.client = type('Client', (), {'session': 'raw-session'})()\n"
        "    def setup_directories(self): pass\n"
        "    async def run(self): pass",
    )
    ns: dict[str, object] = {"__name__": "xkernel_test"}
    exec(compile(source, "XKernel.py", "exec"), ns)
    return ns["Kernel"], kernel_proxy, runtime, base, user_loader, ClientProxy, ModuleKernelProxy, EventProxy


def test_extera_proxy_root_bypasses_direct_client_aliases():
    Kernel, kernel_proxy, runtime, base, user_loader, ClientProxy, ModuleKernelProxy, _ = load_xkernel_with_proxy_stubs()
    kernel = Kernel()

    kernel.set_extera_proxy_all(True)
    kernel.set_extera_proxy_scopes(["root"])

    assert kernel_proxy.get_module_client(kernel, "evaluator", False) is kernel.client
    assert kernel_proxy.ClientProxy(kernel.client, "evaluator") is kernel.client
    assert runtime.ClientProxy(kernel.client, "evaluator") is kernel.client
    assert base.get_module_client(kernel, "evaluator", False) is kernel.client
    assert user_loader.get_module_client(kernel, "evaluator", False) is kernel.client
    assert user_loader.get_module_kernel(kernel, "evaluator", False) is kernel
    assert kernel_proxy.get_module_client(kernel, "evaluator", False).session == "raw-session"

    # Exclusions still receive proxies even in all-mode.
    kernel.set_extera_proxy_modules(["ClientSandboxAudit"])
    assert isinstance(runtime.ClientProxy(kernel.client, "ClientSandboxAudit"), ClientProxy)
    assert isinstance(kernel_proxy.get_module_client(kernel, "ClientSandboxAudit", False), ClientProxy)


def test_extera_proxy_all_mode_treats_module_list_as_exclusions():
    Kernel, kernel_proxy, _, _, _, _, ModuleKernelProxy, EventProxy = load_xkernel_with_proxy_stubs()
    kernel = Kernel()

    kernel.set_extera_proxy_modules(["safe"])
    kernel.set_extera_proxy_all(True)
    kernel.set_extera_proxy_scopes(["root"])

    assert kernel_proxy.get_module_kernel(kernel, "other", False) is kernel
    assert isinstance(kernel_proxy.get_module_kernel(kernel, "safe", False), ModuleKernelProxy)

    event = object()
    assert kernel_proxy.wrap_event_for_module(event, "other", kernel) is event
    assert isinstance(kernel_proxy.wrap_event_for_module(event, "safe", kernel), EventProxy)


def test_extera_proxy_updates_already_loaded_hikka_like_client_attrs():
    Kernel, _, _, _, _, ClientProxy, _, _ = load_xkernel_with_proxy_stubs()
    kernel = Kernel()

    class HikkaLike:
        name = "ClientSandboxAudit"

        def __init__(self, name="ClientSandboxAudit"):
            self.name = name
            self.client = ClientProxy(kernel.client, name)
            self._client = self.client
            self.allmodules = type("AllModules", (), {"_client_proxy": self.client})()

    module = types.ModuleType("ClientSandboxAudit")
    instance = HikkaLike()
    module._class_instance = instance
    kernel.loaded_modules["ClientSandboxAudit"] = module

    assert isinstance(instance._client, ClientProxy)
    kernel.set_extera_proxy_modules(["ClientSandboxAudit"])
    kernel.set_extera_proxy_scopes(["client"])

    assert instance.client is kernel.client
    assert instance._client is kernel.client
    assert instance.allmodules._client_proxy is kernel.client
    assert instance._client.session == "raw-session"

    other_module = types.ModuleType("OtherAudit")
    other_instance = HikkaLike("OtherAudit")
    other_module._class_instance = other_instance
    kernel.loaded_modules["OtherAudit"] = other_module

    # In all-mode the current module list is treated as exclusions.
    kernel.set_extera_proxy_all(True)
    assert isinstance(instance._client, ClientProxy)
    assert other_instance._client is kernel.client

    kernel.set_extera_proxy_modules(["OtherAudit"])
    assert instance._client is kernel.client
    assert isinstance(other_instance._client, ClientProxy)
    assert isinstance(other_instance.client, ClientProxy)
    assert isinstance(other_instance.allmodules._client_proxy, ClientProxy)


def test_core_lib_client_patch_overrides_telegram_identity_kwargs():
    Kernel, *_ = load_xkernel_with_proxy_stubs()

    lib = sys.modules["core.lib"]
    lib.__path__ = []
    base_pkg = types.ModuleType("core.lib.base")
    base_pkg.__path__ = []
    client_module = types.ModuleType("core.lib.base.client")

    calls = []

    def telegram_client(*args, **kwargs):
        calls.append((args, kwargs))
        return {"args": args, "kwargs": kwargs}

    client_module.TelegramClient = telegram_client
    base_pkg.client = client_module
    sys.modules["core.lib.base"] = base_pkg
    sys.modules["core.lib.base.client"] = client_module

    kernel = Kernel()
    status = kernel.patch_core_lib_client(
        device_model="XPhone",
        system_version="XOS 1",
        app_version="XClient 7",
        lang_code="ru",
        system_lang_code="ru-RU",
    )

    assert status["enabled"] is True
    assert status["hook_installed"] is True
    client_module.TelegramClient("session", app_version="old")
    assert calls[-1][1] == {
        "device_model": "XPhone",
        "system_version": "XOS 1",
        "app_version": "XClient 7",
        "lang_code": "ru",
        "system_lang_code": "ru-RU",
    }

    kernel.clear_core_lib_client_patch()
    assert client_module.TelegramClient is telegram_client


def test_core_web_patch_wraps_create_app_and_injects_branding_state():
    Kernel, *_ = load_xkernel_with_proxy_stubs()

    core = sys.modules["core"]
    core.__path__ = []
    web_pkg = types.ModuleType("core.web")
    web_pkg.__path__ = []
    app_module = types.ModuleType("core.web.app")

    def create_app(*args, **kwargs):
        return {}

    app_module.create_app = create_app
    web_pkg.app = app_module
    sys.modules["core.web"] = web_pkg
    sys.modules["core.web.app"] = app_module

    kernel = Kernel()
    status = kernel.patch_core_web(app_name="XPanel", expose_api=False)

    assert status["enabled"] is True
    assert status["hook_installed"] is True
    app = app_module.create_app()
    assert app["xkernel_branding"]["app_name"] == "XPanel"
    assert app["xkernel_branding"]["replacements"] == {
        "MCUB": "XPanel",
        "MCUB - Setup": "XPanel - Setup",
    }

    kernel.clear_core_web_patch()
    assert app_module.create_app is create_app


def test_xkernel_control_methods_are_hidden_from_module_kernel_proxy():
    Kernel, kernel_proxy, _, _, _, _, ModuleKernelProxy, _ = load_xkernel_with_proxy_stubs()
    kernel = Kernel()
    proxy = kernel_proxy.get_module_kernel(kernel, "evil", False)

    for attr_name in (
        "set_extera_proxy_all",
        "set_extera_proxy_scopes",
        "set_extera_proxy_modules",
        "patch_manager",
        "apply_patches",
    ):
        try:
            getattr(proxy, attr_name)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"{attr_name} was exposed through ModuleKernelProxy")

    assert isinstance(proxy, ModuleKernelProxy)
