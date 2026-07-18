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


class AuditMode(str, Enum):
    ALL = "all"
    DENIED = "denied"
    BLOCKED = "blocked"
    OFF = "off"


DEFAULT_MAX_AUDIT_RECORDS = 512


@dataclass
class AuditRecord:
    decision: str
    module: str
    obj_class: str
    action: str
    obj_name: str
    reason: str = ""
    subject_type: str = ""
    target_type: str = ""
    rule_source: str = ""
    permissive: bool = False


class MacEnforcer:
    def __init__(
        self,
        *,
        enabled: bool = False,
        mode: str | EnforceMode = EnforceMode.PERMISSIVE.value,
        audit_mode: str | AuditMode = AuditMode.ALL.value,
        max_audit_records: int = DEFAULT_MAX_AUDIT_RECORDS,
        logger: Any | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.mode = self._mode_value(mode)
        self.audit_mode = self._audit_mode_value(audit_mode)
        self.max_audit_records = self._audit_limit(max_audit_records)
        self._audit_dropped = 0
        self.logger = logger
        self.context = MacContext()
        self.policy = PolicyStore()
        self.permissive_types: set[str] = set()
        self.audit: list[AuditRecord] = []

    @staticmethod
    def _mode_value(mode: str | EnforceMode | None) -> str:
        value = getattr(mode, "value", mode)
        normalized = str(value or EnforceMode.PERMISSIVE.value).strip().casefold()
        allowed = {item.value for item in EnforceMode}
        if normalized not in allowed:
            return EnforceMode.PERMISSIVE.value
        return normalized

    @staticmethod
    def _audit_mode_value(mode: str | AuditMode | None) -> str:
        value = getattr(mode, "value", mode)
        normalized = str(value or AuditMode.ALL.value).strip().casefold()
        allowed = {item.value for item in AuditMode}
        if normalized not in allowed:
            return AuditMode.ALL.value
        return normalized

    @staticmethod
    def _audit_limit(value: int) -> int:
        try:
            limit = int(value)
        except (TypeError, ValueError):
            return DEFAULT_MAX_AUDIT_RECORDS
        return max(0, limit)

    def configure(
        self,
        *,
        enabled: bool | None = None,
        mode: str | None = None,
        audit_mode: str | None = None,
    ) -> None:
        if enabled is not None:
            self.enabled = bool(enabled)
        if mode:
            self.mode = self._mode_value(mode)
        if audit_mode:
            self.audit_mode = self._audit_mode_value(audit_mode)

    def status(self) -> dict[str, Any]:
        audit_denied = sum(1 for record in self.audit if record.decision == "denied")
        audit_blocked = sum(
            1
            for record in self.audit
            if record.decision == "denied" and not record.permissive
        )
        return {
            "available": True,
            "enabled": self.enabled,
            "mode": self.mode,
            "audit_mode": self.audit_mode,
            "audit_size": len(self.audit),
            "audit_limit": self.max_audit_records,
            "audit_dropped": self._audit_dropped,
            "audit_allowed": len(self.audit) - audit_denied,
            "audit_denied": audit_denied,
            "audit_blocked": audit_blocked,
            "contexts": self.context.as_dict(),
            "object_contexts": self.context.objects_as_dict(),
            "permissive_types": sorted(self.permissive_types),
        }

    def clear_audit(self) -> None:
        self.audit.clear()
        self._audit_dropped = 0

    def _append_audit(self, record: AuditRecord) -> None:
        if self.max_audit_records <= 0:
            self._audit_dropped += 1
            return
        self.audit.append(record)
        overflow = len(self.audit) - self.max_audit_records
        if overflow > 0:
            del self.audit[:overflow]
            self._audit_dropped += overflow

    def _should_audit(self, record: AuditRecord) -> bool:
        if self.audit_mode == AuditMode.OFF.value:
            return False
        if self.audit_mode == AuditMode.ALL.value:
            return True
        if record.decision != "denied":
            return False
        if self.audit_mode == AuditMode.DENIED.value:
            return True
        if self.audit_mode == AuditMode.BLOCKED.value:
            return not record.permissive
        return True

    def _record_audit(self, record: AuditRecord) -> None:
        if not self._should_audit(record):
            return
        self._append_audit(record)
        if record.decision == "denied":
            self._log_denied(record)
            return
        self._log_allowed(record)

    def set_type_permissive(
        self, security_type: str, enabled: bool = True
    ) -> None:
        value = MacContext._security_type_value(security_type)
        if enabled:
            self.permissive_types.add(value)
            return
        self.permissive_types.discard(value)

    def clear_type_permissive(self, security_type: str) -> bool:
        value = MacContext._security_type_value(security_type)
        existed = value in self.permissive_types
        self.permissive_types.discard(value)
        return existed

    def is_type_permissive(self, security_type: str) -> bool:
        value = MacContext._security_type_value(security_type)
        return value in self.permissive_types

    @staticmethod
    def _is_enforced(mode: str, subject_type: str, permissive_types: set[str]) -> bool:
        return mode == EnforceMode.ENFORCING.value and subject_type not in permissive_types

    def _log_denied(self, record: AuditRecord) -> None:
        logger = getattr(self, "logger", None)
        if logger is None:
            return
        try:
            logger.warning(
                "[mcmac] avc: denied {%s} for module=%s name=%s "
                "scontext=%s tcontext=%s tclass=%s permissive=%d source=%s",
                record.action,
                record.module,
                record.obj_name,
                record.subject_type or "?",
                record.target_type or "?",
                record.obj_class,
                1 if record.permissive else 0,
                record.rule_source or "policy",
            )
        except Exception:
            pass

    def _log_allowed(self, record: AuditRecord) -> None:
        logger = getattr(self, "logger", None)
        if logger is None:
            return
        debug = getattr(logger, "debug", None)
        if not callable(debug):
            return
        try:
            debug(
                "[mcmac] avc: allowed {%s} for module=%s name=%s "
                "scontext=%s tcontext=%s tclass=%s source=%s",
                record.action,
                record.module,
                record.obj_name,
                record.subject_type or "?",
                record.target_type or "?",
                record.obj_class,
                record.rule_source or "policy",
            )
        except Exception:
            pass

    def check_access(
        self, module_name: str, obj_class: str, action: str, obj_name: str = "*"
    ) -> bool:
        if not self.enabled:
            return True
        module = str(module_name)
        obj_class_value = str(obj_class)
        action_value = str(action)
        obj_name_value = str(obj_name)
        subject = self.context.get_type(module)
        target = self.context.get_object_type(obj_class_value, obj_name_value)
        rule = self.policy.match(
            subject,
            obj_class_value,
            action_value,
            obj_name_value,
            target,
        )
        denied = rule is not None and rule.effect == Effect.DENY.value
        if denied:
            permissive = not self._is_enforced(self.mode, subject, self.permissive_types)
            record = AuditRecord(
                "denied",
                module,
                obj_class_value,
                action_value,
                obj_name_value,
                rule.reason or "policy",
                subject,
                target,
                rule.source,
                permissive,
            )
            self._record_audit(record)
            if not permissive:
                try:
                    from core.lib.loader.kernel_proxy import CallInsecure
                except Exception:
                    raise RuntimeError(
                        f"MCMAC denied {module}: {obj_class_value}:{action_value}:{obj_name_value}"
                    )
                raise CallInsecure(obj_name_value, module)
            return False
        self._record_audit(
            AuditRecord(
                "allowed",
                module,
                obj_class_value,
                action_value,
                obj_name_value,
                getattr(rule, "reason", ""),
                subject,
                target,
                getattr(rule, "source", ""),
                False,
            )
        )
        return True
