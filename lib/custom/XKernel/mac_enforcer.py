from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .mac_context import MacContext
from .mac_policy import PolicyStore
from .mac_types import Effect


class EnforceMode(str, Enum):
    PERMISSIVE = "permissive"
    ENFORCING = "enforcing"


@dataclass
class AuditRecord:
    decision: str
    module: str
    obj_class: str
    action: str
    obj_name: str
    reason: str = ""


class MacEnforcer:
    def __init__(
        self,
        *,
        enabled: bool = False,
        mode: str = EnforceMode.PERMISSIVE.value,
        logger: Any | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.mode = str(mode or EnforceMode.PERMISSIVE.value)
        self.logger = logger
        self.context = MacContext()
        self.policy = PolicyStore()
        self.audit: list[AuditRecord] = []

    def configure(self, *, enabled: bool | None = None, mode: str | None = None) -> None:
        if enabled is not None:
            self.enabled = bool(enabled)
        if mode:
            self.mode = str(mode)

    def status(self) -> dict[str, Any]:
        return {
            "available": True,
            "enabled": self.enabled,
            "mode": self.mode,
            "audit_size": len(self.audit),
            "contexts": self.context.as_dict(),
        }

    def _log_denied(self, record: AuditRecord) -> None:
        logger = getattr(self, "logger", None)
        if logger is None:
            return
        try:
            logger.warning(
                "[mcmac] denied module=%s class=%s action=%s object=%s mode=%s",
                record.module,
                record.obj_class,
                record.action,
                record.obj_name,
                self.mode,
            )
        except Exception:
            pass

    def check_access(self, module_name: str, obj_class: str, action: str, obj_name: str = "*") -> bool:
        if not self.enabled:
            return True
        subject = self.context.get_type(module_name)
        rule = self.policy.match(subject, str(obj_class), str(action), str(obj_name))
        denied = rule is not None and rule.effect == Effect.DENY.value
        if denied:
            record = AuditRecord("denied", module_name, str(obj_class), str(action), str(obj_name), "policy")
            self.audit.append(record)
            self._log_denied(record)
            if self.mode == EnforceMode.ENFORCING.value:
                try:
                    from core.lib.loader.kernel_proxy import CallInsecure
                except Exception:
                    raise RuntimeError(f"MCMAC denied {module_name}: {obj_class}:{action}:{obj_name}")
                raise CallInsecure(str(obj_name), module_name)
            return False
        self.audit.append(AuditRecord("allowed", module_name, str(obj_class), str(action), str(obj_name)))
        return True
