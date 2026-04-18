"""Schema for the Amazon-products example domain.

Edit this file to point the agent at *your* product taxonomy: change the
``CATEGORIES`` enum, add fields, tweak the relaxation order.
"""
from __future__ import annotations

from llm_search_kit.search import SearchField, SearchSchema

CATEGORIES = [
    "shoes",
    "shirts",
    "phones",
    "laptops",
    "headphones",
    "watches",
    "books",
    "kitchen",
]

COLORS = ["red", "blue", "green", "black", "white", "grey", "yellow", "pink"]


def build_schema() -> SearchSchema:
    return SearchSchema(
        fields=[
            SearchField(
                name="category",
                json_type="string",
                enum=CATEGORIES,
                description=(
                    "High-level product category. Pick the closest match from "
                    "the enum, or omit if the user didn't specify one."
                ),
            ),
            SearchField(
                name="brand",
                json_type="string",
                description="Brand name (e.g. Nike, Apple, Sony, Bose).",
            ),
            SearchField(
                name="color",
                json_type="string",
                enum=COLORS,
                description="Primary color of the product.",
            ),
            SearchField(
                name="size",
                json_type="string",
                description=(
                    "Size descriptor as written by the user "
                    "(e.g. '42', 'M', '15 inch')."
                ),
            ),
            SearchField(
                name="min_price",
                json_type="number",
                description="Minimum price in USD.",
            ),
            SearchField(
                name="max_price",
                json_type="number",
                description="Maximum price in USD.",
            ),
            SearchField(
                name="min_rating",
                json_type="number",
                description="Minimum average customer rating (0-5).",
            ),
            SearchField(
                name="prime_only",
                json_type="boolean",
                description="If true, only return Prime-eligible items.",
            ),
        ],
        # Drop the most specific filters first; never drop the category.
        drop_priority=["color", "size", "min_rating", "min_price", "max_price", "brand"],
        core_keys={"category"},
        required=[],
    )
