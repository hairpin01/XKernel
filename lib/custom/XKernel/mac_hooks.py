from __future__ import annotations

import sys
from typing import Any

from .mac_enforcer import EnforceMode, MacEnforcer
from .mac_types import Action, ObjectClass


_TG_METHOD_CLASS = {
    "send_message": ObjectClass.TG_SEND.value,
    "send_file": ObjectClass.TG_SEND.value,
    "edit_message": ObjectClass.TG_SEND.value,
    "delete_messages": ObjectClass.TG_DELETE.value,
    "kick_participant": ObjectClass.TG_ADMIN.value,
    "ban_participant": ObjectClass.TG_ADMIN.value,
    "edit_permissions": ObjectClass.TG_ADMIN.value,
    "edit_admin": ObjectClass.TG_ADMIN.value,
    "edit_profile": ObjectClass.TG_ACCOUNT.value,
}


def ensure_enforcer(kernel: Any) -> MacEnforcer:
    enforcer = getattr(kernel, "_xpatch_mcmac_enforcer", None)
    if enforcer is None:
        enforcer = MacEnforcer(
            enabled=bool(getattr(kernel, "_xpatch_mcmac_enabled", False)),
            mode=str(getattr(kernel, "_xpatch_mcmac_mode", EnforceMode.PERMISSIVE.value)),
            logger=getattr(kernel, "logger", None),
        )
        setattr(kernel, "_xpatch_mcmac_enforcer", enforcer)
    else:
        enforcer.logger = getattr(kernel, "logger", None)
    return enforcer


def configure(kernel: Any, *, enabled: bool | None = None, mode: str | None = None) -> dict[str, Any]:
    enforcer = ensure_enforcer(kernel)
    enforcer.configure(enabled=enabled, mode=mode)
    if enabled is not None:
        setattr(kernel, "_xpatch_mcmac_enabled", bool(enabled))
    if mode is not None:
        setattr(kernel, "_xpatch_mcmac_mode", str(mode))
    return enforcer.status()


def status(kernel: Any) -> dict[str, Any]:
    return ensure_enforcer(kernel).status()


def set_module_type(kernel: Any, module_name: str, security_type: str) -> dict[str, Any]:
    enforcer = ensure_enforcer(kernel)
    enforcer.context.set_type(module_name, security_type)
    return enforcer.status()


def clear_module_type(kernel: Any, module_name: str) -> dict[str, Any]:
    enforcer = ensure_enforcer(kernel)
    enforcer.context.clear_type(module_name)
    return enforcer.status()


def module_type(kernel: Any, module_name: str) -> str:
    return ensure_enforcer(kernel).context.get_type(module_name)


def _classify_client_method(name: str) -> str:
    return _TG_METHOD_CLASS.get(str(name), ObjectClass.TG_SEND.value)


def install_hooks(kernel: Any) -> dict[str, Any]:
    enforcer = ensure_enforcer(kernel)
    if getattr(kernel, "_xpatch_mcmac_hooks_installed", False):
        return enforcer.status()
    try:
        import core.lib.loader.kernel_proxy as kernel_proxy
    except Exception:
        setattr(kernel, "_xpatch_mcmac_hooks_installed", False)
        return enforcer.status()

    original_get_module_kernel = getattr(kernel_proxy, "get_module_kernel", None)
    original_get_module_client = getattr(kernel_proxy, "get_module_client", None)
    original_wrap_event = getattr(kernel_proxy, "wrap_event_for_module", None)

    if callable(original_get_module_kernel):
        def get_module_kernel_with_mcmac(k: Any, module_name: str, is_system: bool) -> Any:
            if k is kernel and not is_system:
                enforcer.check_access(module_name, ObjectClass.KERNEL_ATTR.value, Action.READ.value, "kernel")
            return original_get_module_kernel(k, module_name, is_system)
        get_module_kernel_with_mcmac.__xpatch_mcmac_original__ = original_get_module_kernel
        kernel_proxy.get_module_kernel = get_module_kernel_with_mcmac

    if callable(original_get_module_client):
        def get_module_client_with_mcmac(k: Any, module_name: str, is_system: bool) -> Any:
            client = original_get_module_client(k, module_name, is_system)
            if k is not kernel or is_system:
                return client
            return _MacClientProxy(client, enforcer, module_name)
        get_module_client_with_mcmac.__xpatch_mcmac_original__ = original_get_module_client
        kernel_proxy.get_module_client = get_module_client_with_mcmac

    if callable(original_wrap_event):
        def wrap_event_with_mcmac(event: Any, module_name: str, k: Any) -> Any:
            wrapped = original_wrap_event(event, module_name, k)
            if k is not kernel:
                return wrapped
            return _MacEventProxy(wrapped, enforcer, module_name)
        wrap_event_with_mcmac.__xpatch_mcmac_original__ = original_wrap_event
        kernel_proxy.wrap_event_for_module = wrap_event_with_mcmac

    _patch_imported_aliases(kernel_proxy)
    setattr(kernel, "_xpatch_mcmac_hooks_installed", True)
    return enforcer.status()


def _patch_imported_aliases(kernel_proxy: Any) -> None:
    replacements = {
        "get_module_kernel": getattr(kernel_proxy, "get_module_kernel", None),
        "get_module_client": getattr(kernel_proxy, "get_module_client", None),
        "wrap_event_for_module": getattr(kernel_proxy, "wrap_event_for_module", None),
    }
    originals = {
        name: getattr(wrapper, "__xpatch_mcmac_original__", None)
        for name, wrapper in replacements.items()
        if wrapper is not None
    }
    for module_name, module in list(sys.modules.items()):
        if not str(module_name).startswith("core."):
            continue
        for attr_name, wrapper in replacements.items():
            if wrapper is None or not hasattr(module, attr_name):
                continue
            current = getattr(module, attr_name, None)
            original = originals.get(attr_name)
            if current is original or getattr(current, "__xpatch_mcmac_original__", None) is original:
                setattr(module, attr_name, wrapper)


class _MacClientProxy:
    def __init__(self, client: Any, enforcer: MacEnforcer, module_name: str) -> None:
        object.__setattr__(self, "_client", client)
        object.__setattr__(self, "_enforcer", enforcer)
        object.__setattr__(self, "_module_name", module_name)

    def __getattr__(self, name: str) -> Any:
        attr = getattr(object.__getattribute__(self, "_client"), name)
        if callable(attr):
            obj_class = _classify_client_method(name)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                object.__getattribute__(self, "_enforcer").check_access(
                    object.__getattribute__(self, "_module_name"), obj_class, Action.EXECUTE.value, name
                )
                return attr(*args, **kwargs)
            return wrapper
        return attr


class _MacEventProxy:
    def __init__(self, event: Any, enforcer: MacEnforcer, module_name: str) -> None:
        object.__setattr__(self, "_event", event)
        object.__setattr__(self, "_enforcer", enforcer)
        object.__setattr__(self, "_module_name", module_name)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_event"), name)
