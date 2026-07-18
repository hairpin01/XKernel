from __future__ import annotations

import pytest

from lib.custom.XKernel.mac_context import MacContext
from lib.custom.XKernel.mac_enforcer import EnforceMode, MacEnforcer
from lib.custom.XKernel import mac_hooks
from lib.custom.XKernel.mac_policy import PolicyStore
from lib.custom.XKernel.mac_types import Action, Effect, ObjectClass, SecurityType


def test_mac_context_normalizes_and_validates_module_types():
    context = MacContext()

    context.set_type(" DemoMod ", "TRUSTED")

    assert context.get_type("DemoMod") == SecurityType.TRUSTED.value
    assert context.get_type(" DemoMod ") == SecurityType.TRUSTED.value
    assert context.as_dict() == {"DemoMod": SecurityType.TRUSTED.value}

    with pytest.raises(ValueError):
        context.set_type("", SecurityType.TRUSTED)
    with pytest.raises(ValueError):
        context.set_type("DemoMod", "root")

    assert context.clear_type(" DemoMod ") is True
    assert context.clear_type(" ") is False
    assert context.get_type("DemoMod") == SecurityType.STANDARD.value


def test_mac_enforcer_normalizes_mode_and_caps_audit_records():
    enforcer = MacEnforcer(
        enabled=True,
        mode=" ENFORCING ",
        max_audit_records=2,
    )
    assert enforcer.mode == EnforceMode.ENFORCING.value

    enforcer.configure(mode="invalid")
    assert enforcer.mode == EnforceMode.PERMISSIVE.value
    enforcer.context.set_type("NoisyMod", SecurityType.UNTRUSTED)

    for obj_name in ("first", "second", "third"):
        assert (
            enforcer.check_access(
                "NoisyMod",
                ObjectClass.TG_DELETE.value,
                Action.EXECUTE.value,
                obj_name,
            )
            is False
        )

    status = enforcer.status()
    assert [record.obj_name for record in enforcer.audit] == ["second", "third"]
    assert status["contexts"] == {"NoisyMod": SecurityType.UNTRUSTED.value}
    assert status["object_contexts"] == {}
    assert status["permissive_types"] == []
    assert {
        key: status[key]
        for key in (
            "available",
            "enabled",
            "mode",
            "audit_size",
            "audit_limit",
            "audit_dropped",
            "audit_allowed",
            "audit_denied",
        )
    } == {
        "available": True,
        "enabled": True,
        "mode": EnforceMode.PERMISSIVE.value,
        "audit_size": 2,
        "audit_limit": 2,
        "audit_dropped": 1,
        "audit_allowed": 0,
        "audit_denied": 2,
    }

    enforcer.clear_audit()

    assert enforcer.status()["audit_size"] == 0
    assert enforcer.status()["audit_dropped"] == 0


def test_mac_enforcer_zero_audit_limit_keeps_counters_only():
    enforcer = MacEnforcer(enabled=True, max_audit_records=0)

    assert enforcer.check_access(
        "StdMod",
        ObjectClass.TG_SEND.value,
        Action.EXECUTE.value,
        "send_message",
    ) is True

    status = enforcer.status()
    assert status["audit_size"] == 0
    assert status["audit_dropped"] == 1


def test_policy_store_respects_explicit_empty_rules():
    store = PolicyStore([])

    assert (
        store.match(
            SecurityType.SYSTEM.value,
            ObjectClass.TG_SEND.value,
            Action.EXECUTE.value,
            "send_message",
        )
        is None
    )


def test_mac_context_object_labels_support_exact_and_glob_patterns():
    context = MacContext()

    context.set_object_type(ObjectClass.TG_SEND.value, "secret-*", "untrusted")
    context.set_object_type(ObjectClass.TG_SEND.value, "secret-admin", "trusted")

    assert (
        context.get_object_type(ObjectClass.TG_SEND.value, "secret-admin")
        == SecurityType.TRUSTED.value
    )
    assert (
        context.get_object_type(ObjectClass.TG_SEND.value, "secret-chat")
        == SecurityType.UNTRUSTED.value
    )
    assert (
        context.get_object_type(ObjectClass.TG_DELETE.value, "secret-chat")
        == SecurityType.STANDARD.value
    )
    assert context.objects_as_dict() == {
        "tg_send:secret-*": SecurityType.UNTRUSTED.value,
        "tg_send:secret-admin": SecurityType.TRUSTED.value,
    }

    with pytest.raises(ValueError):
        context.set_object_type("", "secret", SecurityType.TRUSTED)

    assert context.clear_object_type(ObjectClass.TG_SEND.value, "secret-admin") is True
    assert context.clear_object_type(" ", "secret-admin") is False


def test_policy_store_matches_selinux_like_target_type_before_default_allow():
    store = PolicyStore()

    store.deny(
        SecurityType.UNTRUSTED.value,
        ObjectClass.TG_SEND.value,
        Action.EXECUTE.value,
        "secret-*",
        target=SecurityType.QUARANTINE.value,
        source="test-policy",
        reason="target quarantine",
    )

    deny_rule = store.match(
        SecurityType.UNTRUSTED.value,
        ObjectClass.TG_SEND.value,
        Action.EXECUTE.value,
        "secret-chat",
        SecurityType.QUARANTINE.value,
    )
    allow_rule = store.match(
        SecurityType.UNTRUSTED.value,
        ObjectClass.TG_SEND.value,
        Action.EXECUTE.value,
        "secret-chat",
        SecurityType.STANDARD.value,
    )

    assert deny_rule is not None
    assert deny_rule.effect == Effect.DENY.value
    assert deny_rule.target == SecurityType.QUARANTINE.value
    assert deny_rule.source == "test-policy"
    assert allow_rule is not None
    assert allow_rule.effect == Effect.ALLOW.value
    assert store.rules[-2] is deny_rule


def test_mac_enforcer_records_avc_context_and_permissive_domains():
    enforcer = MacEnforcer(enabled=True, mode=EnforceMode.ENFORCING.value)
    enforcer.context.set_type("BadMod", SecurityType.UNTRUSTED)
    enforcer.context.set_object_type(
        ObjectClass.TG_SEND.value,
        "secret-chat",
        SecurityType.QUARANTINE,
    )
    enforcer.policy.deny(
        SecurityType.UNTRUSTED.value,
        ObjectClass.TG_SEND.value,
        Action.EXECUTE.value,
        "secret-*",
        target=SecurityType.QUARANTINE.value,
        source="unit-test",
        reason="secret target",
    )

    with pytest.raises(RuntimeError):
        enforcer.check_access(
            "BadMod",
            ObjectClass.TG_SEND.value,
            Action.EXECUTE.value,
            "secret-chat",
        )

    enforced_record = enforcer.audit[-1]
    assert enforced_record.decision == "denied"
    assert enforced_record.subject_type == SecurityType.UNTRUSTED.value
    assert enforced_record.target_type == SecurityType.QUARANTINE.value
    assert enforced_record.rule_source == "unit-test"
    assert enforced_record.reason == "secret target"
    assert enforced_record.permissive is False

    enforcer.set_type_permissive(SecurityType.UNTRUSTED.value)

    assert (
        enforcer.check_access(
            "BadMod",
            ObjectClass.TG_SEND.value,
            Action.EXECUTE.value,
            "secret-chat",
        )
        is False
    )

    permissive_record = enforcer.audit[-1]
    status = enforcer.status()
    assert permissive_record.permissive is True
    assert status["object_contexts"] == {
        "tg_send:secret-chat": SecurityType.QUARANTINE.value
    }
    assert status["permissive_types"] == [SecurityType.UNTRUSTED.value]

    assert enforcer.clear_type_permissive(SecurityType.UNTRUSTED.value) is True
    assert enforcer.is_type_permissive(SecurityType.UNTRUSTED.value) is False


def test_mac_hooks_expose_selinux_like_runtime_controls():
    kernel = type(
        "Kernel",
        (),
        {
            "_xpatch_mcmac_enabled": True,
            "_xpatch_mcmac_mode": "invalid",
            "logger": None,
        },
    )()

    status = mac_hooks.configure(kernel, enabled=True, mode="invalid")
    assert status["mode"] == EnforceMode.PERMISSIVE.value
    assert kernel._xpatch_mcmac_mode == EnforceMode.PERMISSIVE.value

    mac_hooks.set_object_type(
        kernel,
        ObjectClass.TG_SEND.value,
        "secret-chat",
        SecurityType.QUARANTINE.value,
    )
    mac_hooks.set_permissive_type(kernel, SecurityType.UNTRUSTED.value)

    assert (
        mac_hooks.object_type(kernel, ObjectClass.TG_SEND.value, "secret-chat")
        == SecurityType.QUARANTINE.value
    )
    assert mac_hooks.status(kernel)["permissive_types"] == [
        SecurityType.UNTRUSTED.value
    ]

    mac_hooks.clear_object_type(kernel, ObjectClass.TG_SEND.value, "secret-chat")
    mac_hooks.clear_permissive_type(kernel, SecurityType.UNTRUSTED.value)
    mac_hooks.clear_audit(kernel)

    assert (
        mac_hooks.object_type(kernel, ObjectClass.TG_SEND.value, "secret-chat")
        == SecurityType.STANDARD.value
    )
    assert mac_hooks.status(kernel)["permissive_types"] == []
