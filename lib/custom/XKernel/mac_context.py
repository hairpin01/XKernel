from __future__ import annotations

from fnmatch import fnmatchcase

from .mac_types import SecurityType


class MacContext:
    def __init__(self) -> None:
        self._types: dict[str, str] = {}
        self._object_types: dict[tuple[str, str], str] = {}

    @staticmethod
    def _module_key(module_name: str) -> str:
        return str(module_name or "").strip()

    @staticmethod
    def _security_type_value(security_type: str | SecurityType) -> str:
        value = getattr(security_type, "value", security_type)
        normalized = str(value or "").strip().casefold()
        allowed = {item.value for item in SecurityType}
        if normalized not in allowed:
            raise ValueError(f"unsupported MCMAC security type: {value!r}")
        return normalized

    @staticmethod
    def _object_key(obj_class: str, obj_name: str) -> tuple[str, str]:
        return str(obj_class or "").strip(), str(obj_name or "").strip()

    @staticmethod
    def _match(value: str, pattern: str) -> bool:
        return pattern == "*" or fnmatchcase(value, pattern)

    def has_type(self, module_name: str) -> bool:
        key = self._module_key(module_name)
        return bool(key) and key in self._types

    def set_type(self, module_name: str, security_type: str | SecurityType) -> None:
        key = self._module_key(module_name)
        if not key:
            raise ValueError("MCMAC module name must not be empty")
        self._types[key] = self._security_type_value(security_type)

    def clear_type(self, module_name: str) -> bool:
        key = self._module_key(module_name)
        if not key:
            return False
        return self._types.pop(key, None) is not None

    def get_type(self, module_name: str) -> str:
        key = self._module_key(module_name)
        if not key:
            return SecurityType.STANDARD.value
        return self._types.get(key, SecurityType.STANDARD.value)

    def set_object_type(
        self,
        obj_class: str,
        obj_name: str,
        security_type: str | SecurityType,
    ) -> None:
        key = self._object_key(obj_class, obj_name)
        if not all(key):
            raise ValueError("MCMAC object class and name must not be empty")
        self._object_types[key] = self._security_type_value(security_type)

    def clear_object_type(self, obj_class: str, obj_name: str) -> bool:
        key = self._object_key(obj_class, obj_name)
        if not all(key):
            return False
        return self._object_types.pop(key, None) is not None

    def get_object_type(self, obj_class: str, obj_name: str) -> str:
        key = self._object_key(obj_class, obj_name)
        if not all(key):
            return SecurityType.STANDARD.value
        exact = self._object_types.get(key)
        if exact is not None:
            return exact
        for (class_pattern, name_pattern), security_type in reversed(
            self._object_types.items()
        ):
            if self._match(key[0], class_pattern) and self._match(key[1], name_pattern):
                return security_type
        return SecurityType.STANDARD.value

    def as_dict(self) -> dict[str, str]:
        return dict(self._types)

    def objects_as_dict(self) -> dict[str, str]:
        return {
            f"{obj_class}:{obj_name}": security_type
            for (obj_class, obj_name), security_type in self._object_types.items()
        }
