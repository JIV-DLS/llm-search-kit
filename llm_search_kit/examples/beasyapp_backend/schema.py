"""``SearchSchema`` for Armand's Beasyapp listings backend.

The set of fields here is the *intent surface* exposed to the LLM. They
are deliberately **named in snake_case** (kit convention) and translated
to camelCase by :class:`BeasyappCatalog` before being POSTed to Spring.

Drop priority encodes the assistant's behaviour when zero results come
back: drop the most specific filters first, never drop the user's
free-text intent, and treat ``category_ids`` as core (we never silently
broaden the category since that is usually what the user actually meant).

Note: ``brand_ids`` and ``category_ids`` are integer ids -- in production
you will want to either (a) preload these mappings from the backend's
``/categories`` and ``/brands`` endpoints and inject them as enums, or
(b) write a second skill that lets the LLM look up an id by name.

For the demo we keep them as free integers and rely on the assistant's
context-window knowledge to map "Samsung" to a brand id when the user
explicitly mentions one (the soul.md prompt tells it to omit the filter
when unsure -- i.e. fall back to free-text matching).
"""
from __future__ import annotations

from llm_search_kit.search import SearchField, SearchSchema


# Beasy's deliveryType is an enum on the backend.
DELIVERY_TYPES = ["USER", "ASIGANME"]


def build_schema() -> SearchSchema:
    return SearchSchema(
        fields=[
            SearchField(
                name="category_ids",
                json_type="array",
                item_type="integer",
                description=(
                    "List of category ids the user is browsing. Omit if "
                    "the user did not specify a category."
                ),
            ),
            SearchField(
                name="brand_ids",
                json_type="array",
                item_type="integer",
                description=(
                    "List of brand ids. Only set when the user explicitly "
                    "names a brand AND you are confident of its id; "
                    "otherwise leave the brand to free-text query."
                ),
            ),
            SearchField(
                name="min_price",
                json_type="number",
                description="Minimum price in FCFA (inclusive).",
            ),
            SearchField(
                name="max_price",
                json_type="number",
                description="Maximum price in FCFA (inclusive).",
            ),
            SearchField(
                name="min_rating",
                json_type="number",
                description="Minimum average customer rating (0-5).",
            ),
            SearchField(
                name="color",
                json_type="string",
                description=(
                    "Color hex code as exposed by the facets endpoint, "
                    "e.g. \"#000000\" for black, \"#808080\" for grey. "
                    "Map common color words yourself when the user says "
                    "\"black\", \"red\", etc."
                ),
            ),
            SearchField(
                name="city",
                json_type="string",
                description="City name (e.g. \"Lomé\", \"Paris\").",
            ),
            SearchField(
                name="country",
                json_type="string",
                description="Two-letter country code (\"TG\", \"FR\", ...).",
            ),
            SearchField(
                name="debatable",
                json_type="boolean",
                description="If true, only return listings whose price is negotiable.",
            ),
            SearchField(
                name="has_discount",
                json_type="boolean",
                description="If true, only return discounted listings.",
            ),
            SearchField(
                name="in_stock",
                json_type="boolean",
                description="If true, only return in-stock listings.",
            ),
            SearchField(
                name="delivery_type",
                json_type="string",
                enum=DELIVERY_TYPES,
                description=(
                    "Delivery channel. \"ASIGANME\" = handled by the "
                    "platform's logistics, \"USER\" = the seller delivers."
                ),
            ),
            SearchField(
                name="latitude",
                json_type="number",
                description="User latitude for proximity ranking.",
            ),
            SearchField(
                name="longitude",
                json_type="number",
                description="User longitude for proximity ranking.",
            ),
            SearchField(
                name="radius_km",
                json_type="number",
                description=(
                    "Search radius in km (only used when latitude+longitude "
                    "are also set). Default 50."
                ),
            ),
            SearchField(
                name="filter_by_radius",
                json_type="boolean",
                description=(
                    "If true, hide results outside radius_km. If false "
                    "(default), only sort by proximity."
                ),
            ),
        ],
        # Drop most-specific first, keep category as the user's anchor.
        drop_priority=[
            "color",
            "min_rating",
            "has_discount",
            "debatable",
            "in_stock",
            "delivery_type",
            "min_price",
            "max_price",
            "brand_ids",
            "city",
            "country",
            "filter_by_radius",
            "radius_km",
        ],
        core_keys={"category_ids"},
        required=[],
    )
