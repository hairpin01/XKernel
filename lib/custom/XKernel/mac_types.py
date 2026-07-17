from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SecurityType(str, Enum):
    SYSTEM = "system"
    TRUSTED = "trusted"
    STANDARD = "standard"
    UNTRUSTED = "untrusted"
    QUARANTINE = "quarantine"


class ObjectClass(str, Enum):
    KERNEL_ATTR = "kernel_attr"
    TG_SEND = "tg_send"
    TG_DELETE = "tg_delete"
    TG_ADMIN = "tg_admin"
    TG_ACCOUNT = "tg_account"
    SUBPROCESS = "subprocess"
    NETWORK = "network"
    FILESYSTEM = "fs"
    INLINE = "inline"
    CONFIG_DB = "config_db"
    MODULE_LOAD = "module_load"


class Action(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    CONNECT = "connect"
    REGISTER = "register"


class Effect(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class PolicyRule:
    subject: str
    obj_class: str
    action: str
    pattern: str = "*"
    effect: str = Effect.ALLOW.value
