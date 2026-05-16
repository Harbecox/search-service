from __future__ import annotations

from pydantic import BaseModel, Field


class ProductDTO(BaseModel):
    source_key: str
    source_id: str
    name: str
    description: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    price: float | None = None
    category: str | None = None
    image_url: str | None = None
    meta: dict = Field(default_factory=dict)  # type: ignore[type-arg]

    @property
    def global_id(self) -> str:
        return f"{self.source_key}:{self.source_id}"

    def to_embedding_text(self) -> str:
        # Name is repeated for weight; attributes appended for semantic richness.
        parts = [self.name, self.name]
        if self.attributes:
            attrs = ", ".join(f"{k}={v}" for k, v in self.attributes.items())
            parts.append(f"Характеристики: {attrs}")
        if self.description:
            parts.append(self.description)
        if self.category:
            parts.append(f"Категория: {self.category}")
        return ". ".join(parts)
