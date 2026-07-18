from __future__ import annotations

from fnmatch import fnmatchcase

from .mac_types import Effect, ObjectClass, PolicyRule, SecurityType


class PolicyStore:
    def __init__(self, rules: list[PolicyRule] | None = None) -> None:
        self.rules = self.default_rules() if rules is None else list(rules)

    @staticmethod
    def _is_default_allow(rule: PolicyRule) -> bool:
        return (
            rule.subject == "*"
            and rule.obj_class == "*"
            and rule.action == "*"
            and rule.pattern == "*"
            and rule.effect == Effect.ALLOW.value
            and rule.target == "*"
        )

    def add_rule(self, rule: PolicyRule, *, before_default_allow: bool = True) -> None:
        if before_default_allow and self.rules and self._is_default_allow(self.rules[-1]):
            self.rules.insert(len(self.rules) - 1, rule)
            return
        self.rules.append(rule)

    def allow(
        self,
        subject: str,
        obj_class: str,
        action: str,
        pattern: str = "*",
        *,
        target: str = "*",
        source: str = "runtime",
        reason: str = "",
    ) -> None:
        self.add_rule(
            PolicyRule(
                subject,
                obj_class,
                action,
                pattern,
                Effect.ALLOW.value,
                target,
                source,
                reason,
            )
        )

    def deny(
        self,
        subject: str,
        obj_class: str,
        action: str,
        pattern: str = "*",
        *,
        target: str = "*",
        source: str = "runtime",
        reason: str = "",
    ) -> None:
        self.add_rule(
            PolicyRule(
                subject,
                obj_class,
                action,
                pattern,
                Effect.DENY.value,
                target,
                source,
                reason,
            )
        )

    @staticmethod
    def default_rules() -> list[PolicyRule]:
        return [
            PolicyRule(SecurityType.SYSTEM.value, "*", "*", "*", Effect.ALLOW.value),
            PolicyRule(SecurityType.QUARANTINE.value, "*", "*", "*", Effect.DENY.value),
            PolicyRule(
                SecurityType.TRUSTED.value,
                ObjectClass.SUBPROCESS.value,
                "*",
                "*",
                Effect.DENY.value,
            ),
            PolicyRule(
                SecurityType.STANDARD.value,
                ObjectClass.TG_ADMIN.value,
                "*",
                "*",
                Effect.DENY.value,
            ),
            PolicyRule(
                SecurityType.STANDARD.value,
                ObjectClass.TG_ACCOUNT.value,
                "*",
                "*",
                Effect.DENY.value,
            ),
            PolicyRule(
                SecurityType.STANDARD.value,
                ObjectClass.SUBPROCESS.value,
                "*",
                "*",
                Effect.DENY.value,
            ),
            PolicyRule(
                SecurityType.UNTRUSTED.value,
                ObjectClass.TG_DELETE.value,
                "*",
                "*",
                Effect.DENY.value,
            ),
            PolicyRule(
                SecurityType.UNTRUSTED.value,
                ObjectClass.TG_ADMIN.value,
                "*",
                "*",
                Effect.DENY.value,
            ),
            PolicyRule(
                SecurityType.UNTRUSTED.value,
                ObjectClass.TG_ACCOUNT.value,
                "*",
                "*",
                Effect.DENY.value,
            ),
            PolicyRule(
                SecurityType.UNTRUSTED.value,
                ObjectClass.SUBPROCESS.value,
                "*",
                "*",
                Effect.DENY.value,
            ),
            PolicyRule(
                SecurityType.UNTRUSTED.value,
                ObjectClass.NETWORK.value,
                "*",
                "*",
                Effect.DENY.value,
            ),
            PolicyRule(
                SecurityType.UNTRUSTED.value,
                ObjectClass.CONFIG_DB.value,
                "write",
                "*",
                Effect.DENY.value,
            ),
            PolicyRule(
                SecurityType.UNTRUSTED.value,
                ObjectClass.KERNEL_ATTR.value,
                "write",
                "*",
                Effect.DENY.value,
            ),
            PolicyRule(
                SecurityType.UNTRUSTED.value,
                ObjectClass.MODULE_LOAD.value,
                "*",
                "*",
                Effect.DENY.value,
            ),
            PolicyRule("*", "*", "*", "*", Effect.ALLOW.value),
        ]

    @staticmethod
    def _match(value: str, pattern: str) -> bool:
        return pattern == "*" or fnmatchcase(value, pattern)

    def match(
        self,
        subject: str,
        obj_class: str,
        action: str,
        obj_name: str,
        target_type: str = "*",
    ) -> PolicyRule | None:
        for rule in self.rules:
            if not self._match(subject, rule.subject):
                continue
            if not self._match(target_type, rule.target):
                continue
            if not self._match(obj_class, rule.obj_class):
                continue
            if not self._match(action, rule.action):
                continue
            if not self._match(obj_name, rule.pattern):
                continue
            return rule
        return None
