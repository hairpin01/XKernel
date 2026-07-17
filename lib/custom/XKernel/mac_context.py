from __future__ import annotations

from .mac_types import SecurityType


class MacContext:
    def __init__(self) -> None:
        self._types: dict[str, str] = {}

    def set_type(self, module_name: str, security_type: str | SecurityType) -> None:
        self._types[str(module_name)] = str(getattr(security_type, "value", security_type))

    def clear_type(self, module_name: str) -> bool:
        return self._types.pop(str(module_name), None) is not None

    def get_type(self, module_name: str) -> str:
        return self._types.get(str(module_name), SecurityType.STANDARD.value)

    def as_dict(self) -> dict[str, str]:
        return dict(self._types)
