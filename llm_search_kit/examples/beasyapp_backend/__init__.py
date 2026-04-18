"""Example adapter for Armand's Spring Boot ``/api/v1/listings/search`` API.

Maps the kit's generic ``CatalogBackend`` shape to his exact
``SearchRequest`` / ``SearchResponse`` contract, scrubs PII out of the
listings before returning them to the LLM, and exposes the response
facets as ``metadata`` so the assistant can present them to the user.

This is the recommended *real-world* example for adopters who already
have an existing Java/Kotlin/Node backend with its own search endpoint
and just want to drop the kit in front of it -- no ETL, no second DB.
"""
from .catalog import (
    BeasyappCatalog,
    BeasyappAPIError,
    scrub_listing,
)
from .schema import build_schema

__all__ = [
    "BeasyappCatalog",
    "BeasyappAPIError",
    "build_schema",
    "scrub_listing",
]
