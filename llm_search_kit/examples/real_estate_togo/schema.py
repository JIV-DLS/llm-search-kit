"""Real-estate (Togo) schema.

Replicates the searchable surface of the original rede project's
``SearchPropertiesSkill`` (see
``rede/backend/chatbot-service/agent/skills/search_properties.py``).
"""
from __future__ import annotations

from llm_search_kit.search import SearchField, SearchSchema

PROPERTY_TYPES = [
    "maison", "villa", "appartement", "chambre", "terrain", "boutique",
    "studio", "duplex", "immeuble", "demi_lot", "bureau", "entrepot",
]

TRANSACTION_TYPES = ["location", "vente"]

SORT_BY = ["relevance", "price_asc", "price_desc", "newest"]

AMENITIES = [
    "wc_douche_interne", "wc_douche_externe", "cuisine_interne",
    "cuisine_externe", "garage", "climatisation", "compteur_cash_power",
    "compteur_eau", "eau_forage", "wifi", "cour", "veranda", "carrelage",
    "dalle", "cloture", "placard", "dependance", "boutique_integree",
    "meuble", "piscine",
]

TOGO_CITIES = [
    "Lomé", "Kara", "Sokodé", "Kpalimé", "Atakpamé", "Dapaong",
    "Tsévié", "Aného", "Bassar", "Tchamba", "Notsé",
]


def build_schema() -> SearchSchema:
    return SearchSchema(
        fields=[
            SearchField(
                name="city",
                json_type="string",
                enum=TOGO_CITIES,
                description="City in Togo (e.g. Lomé, Kara, Sokodé).",
            ),
            SearchField(
                name="quartier",
                json_type="string",
                description="Neighborhood / quartier within the city.",
            ),
            SearchField(
                name="property_type",
                json_type="string",
                enum=PROPERTY_TYPES,
                description="Type of property.",
            ),
            SearchField(
                name="transaction_type",
                json_type="string",
                enum=TRANSACTION_TYPES,
                description="'location' (rent) or 'vente' (sale). Defaults to 'location'.",
            ),
            SearchField(
                name="min_price",
                json_type="number",
                description="Minimum price in FCFA.",
            ),
            SearchField(
                name="max_price",
                json_type="number",
                description="Maximum price in FCFA. Note: '100k' = 100000, '1M' = 1000000.",
            ),
            SearchField(
                name="min_chambres",
                json_type="integer",
                description="Minimum number of bedrooms.",
            ),
            SearchField(
                name="amenities",
                json_type="array",
                item_type="string",
                description="Required amenities (e.g. climatisation, garage, meuble).",
            ),
            SearchField(
                name="exclude_property_types",
                json_type="array",
                item_type="string",
                description=(
                    "Property types to EXCLUDE. Use for 'logement / habitation' "
                    "queries to filter out land plots: ['terrain', 'demi_lot']."
                ),
            ),
        ],
        # Same priority as rede/backend/chatbot-service/app/services/filter_relaxation.py.
        drop_priority=[
            "amenities",
            "max_price",
            "min_price",
            "min_chambres",
            "quartier",
            "property_type",
        ],
        # Always keep at least the city and transaction type.
        core_keys={"city", "transaction_type"},
    )
