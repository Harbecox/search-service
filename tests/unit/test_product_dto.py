from __future__ import annotations

import pytest

from search_service.dto.product import ProductDTO


def test_global_id() -> None:
    p = ProductDTO(source_key="shop", source_id="42", name="Widget")
    assert p.global_id == "shop:42"


def test_to_embedding_text_minimal() -> None:
    p = ProductDTO(source_key="shop", source_id="1", name="Widget")
    text = p.to_embedding_text()
    # Name repeated twice for weight
    assert text.count("Widget") == 2


def test_to_embedding_text_full() -> None:
    p = ProductDTO(
        source_key="shop",
        source_id="1",
        name="Bolt M6",
        description="High-strength steel bolt",
        attributes={"material": "steel", "size": "M6"},
        category="Fasteners",
    )
    text = p.to_embedding_text()
    assert "Bolt M6" in text
    assert "Характеристики:" in text
    assert "material=steel" in text
    assert "size=M6" in text
    assert "High-strength steel bolt" in text
    assert "Категория: Fasteners" in text


def test_source_id_is_str() -> None:
    p = ProductDTO(source_key="s", source_id="123", name="X")
    assert isinstance(p.source_id, str)
