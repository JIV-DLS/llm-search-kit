"""Elasticsearch CatalogBackend example.

Implements ``llm_search_kit.search.CatalogBackend`` against an Elasticsearch
8.x ``products`` index. See ``catalog.py`` for the adapter and ``run.py``
for a tiny seeding + one-shot search script.
"""
from .catalog import ElasticsearchCatalog, build_default_index_mapping

__all__ = ["ElasticsearchCatalog", "build_default_index_mapping"]
