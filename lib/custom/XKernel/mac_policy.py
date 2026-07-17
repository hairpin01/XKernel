from __future__ import annotations

from fnmatch import fnmatchcase

from .mac_types import Effect, ObjectClass, PolicyRule, SecurityType


class PolicyStore:
    def __init__(self, rules: list[PolicyRule] | None = None) -> None:
        self.rules = rules or self.default_rules()

    @staticmethod
    def default_rules() -> list[PolicyRule]:
        return [
            PolicyRule(SecurityType.SYSTEM.value, "*", "*", "*", Effect.ALLOW.value),
            PolicyRule(SecurityType.QUARANTINE.value, "*", "*", "*", Effect.DENY.value),
            PolicyRule(SecurityType.TRUSTED.value, ObjectClass.SUBPROCESS.value, "*", "*", Effect.DENY.value),
            PolicyRule(SecurityType.UNTRUSTED.value, ObjectClass.TG_DELETE.value, "*", "*", Effect.DENY.value),
            PolicyRule(SecurityType.UNTRUSTED.value, ObjectClass.TG_ADMIN.value, "*", "*", Effect.DENY.value),
            PolicyRule(SecurityType.UNTRUSTED.value, ObjectClass.TG_ACCOUNT.value, "*", "*", Effect.DENY.value),
            PolicyRule(SecurityType.UNTRUSTED.value, ObjectClass.SUBPROCESS.value, "*", "*", Effect.DENY.value),
            PolicyRule(SecurityType.UNTRUSTED.value, ObjectClass.NETWORK.value, "*", "*", Effect.DENY.value),
            PolicyRule("*", "*", "*", "*", Effect.ALLOW.value),
        ]

    @staticmethod
    def _match(value: str, pattern: str) -> bool:
        return pattern == "*" or fnmatchcase(value, pattern)

    def match(self, subject: str, obj_class: str, action: str, obj_name: str) -> PolicyRule | None:
        for rule in self.rules:
            if not self._match(subject, rule.subject):
                continue
            if not self._match(obj_class, rule.obj_class):
                continue
            if not self._match(action, rule.action):
                continue
            if not self._match(obj_name, rule.pattern):
                continue
            return rule
        return None
