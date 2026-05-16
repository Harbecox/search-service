from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from search_service.config import Settings
    from search_service.providers.base import ProductProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, "ProductProvider"] = {}

    def register(self, provider: "ProductProvider") -> None:
        self._providers[provider.source_key()] = provider

    def get(self, source_key: str) -> "ProductProvider":
        return self._providers[source_key]

    def all(self) -> list["ProductProvider"]:
        return list(self._providers.values())

    def load_from_settings(self, settings: "Settings") -> None:
        raw = settings.providers_classes.strip()
        if not raw:
            return
        for dotted_path in [p.strip() for p in raw.split(",") if p.strip()]:
            module_path, class_name = dotted_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            instance = cls(mysql_dsn=settings.mysql_dsn)
            self.register(instance)
