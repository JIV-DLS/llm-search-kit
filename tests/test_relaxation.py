"""Tests for build_relaxation_levels.

The first batch of tests asserts parity with the original rede behaviour
(see ``rede/backend/chatbot-service/app/services/filter_relaxation.py``).
"""
from __future__ import annotations

import pytest

from llm_search_kit.search import build_relaxation_levels


# Drop priority that mirrors the original rede ladder for real-estate.
RE_DROP = ["amenities", "max_price", "min_price", "min_chambres", "quartier", "property_type"]
RE_CORE = {"city", "transaction_type"}


def test_empty_filters_returns_single_empty_level():
    assert build_relaxation_levels({}, drop_priority=RE_DROP, core_keys=RE_CORE) == [{}]


def test_only_core_filters_yields_single_level():
    filters = {"city": "Lomé", "transaction_type": "location"}
    levels = build_relaxation_levels(filters, drop_priority=RE_DROP, core_keys=RE_CORE)
    assert levels == [filters]


def test_drops_amenities_first():
    filters = {
        "city": "Lomé",
        "property_type": "villa",
        "amenities": ["climatisation"],
        "max_price": 500000,
    }
    levels = build_relaxation_levels(filters, drop_priority=RE_DROP, core_keys=RE_CORE)
    assert levels[0] == filters
    assert "amenities" not in levels[1]
    assert "max_price" in levels[1]


def test_full_ladder_for_realistic_filter_set():
    filters = {
        "city": "Lomé",
        "transaction_type": "location",
        "quartier": "Agoè",
        "property_type": "villa",
        "min_chambres": 3,
        "max_price": 500000,
        "amenities": ["piscine"],
    }
    levels = build_relaxation_levels(filters, drop_priority=RE_DROP, core_keys=RE_CORE)
    # Level 0 = original
    assert levels[0] == filters
    # Each subsequent level drops exactly the next priority key.
    expected_dropped = ["amenities", "max_price", "min_chambres", "quartier", "property_type"]
    for i, key in enumerate(expected_dropped, start=1):
        assert key not in levels[i], f"level {i} should not contain {key}"
    # Final level contains only core keys (city + transaction_type).
    assert set(levels[-1].keys()) == RE_CORE


def test_strips_empty_values():
    filters = {"city": "Lomé", "quartier": "", "amenities": [], "transaction_type": "location"}
    levels = build_relaxation_levels(filters, drop_priority=RE_DROP, core_keys=RE_CORE)
    assert levels[0] == {"city": "Lomé", "transaction_type": "location"}


def test_consecutive_levels_are_strictly_different():
    filters = {"city": "Lomé", "transaction_type": "location", "amenities": ["wifi"]}
    levels = build_relaxation_levels(filters, drop_priority=RE_DROP, core_keys=RE_CORE)
    for a, b in zip(levels, levels[1:]):
        assert a != b


def test_unrelated_drop_keys_are_skipped():
    filters = {"city": "Lomé", "transaction_type": "location"}
    levels = build_relaxation_levels(
        filters, drop_priority=["amenities", "min_chambres"], core_keys=RE_CORE,
    )
    # Only the original level remains: nothing to drop.
    assert levels == [filters]


def test_core_keys_never_dropped_even_if_in_priority():
    filters = {"city": "Lomé", "transaction_type": "location", "extra": "foo"}
    levels = build_relaxation_levels(
        filters,
        drop_priority=["city", "transaction_type", "extra"],
        core_keys={"city", "transaction_type"},
    )
    # 'city' and 'transaction_type' must not be dropped, only 'extra' goes.
    assert all("city" in lvl for lvl in levels)
    assert all("transaction_type" in lvl for lvl in levels)
    assert "extra" not in levels[-1]


# --- Amazon-flavoured ladder ---------------------------------------------

AMZ_DROP = ["color", "size", "min_rating", "min_price", "max_price", "brand"]
AMZ_CORE = {"category"}


def test_amazon_ladder_drops_color_first():
    filters = {
        "category": "shoes",
        "brand": "Nike",
        "color": "red",
        "max_price": 100,
    }
    levels = build_relaxation_levels(filters, drop_priority=AMZ_DROP, core_keys=AMZ_CORE)
    assert levels[0] == filters
    assert "color" not in levels[1]
    # Eventually drops brand, then keeps just category.
    assert levels[-1] == {"category": "shoes"}
