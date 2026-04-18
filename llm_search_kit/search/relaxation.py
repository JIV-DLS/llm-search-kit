"""Progressive filter relaxation.

When a strict search returns 0 results, you usually want to retry with a
relaxed filter set rather than telling the user "nothing found". The
``build_relaxation_levels`` function returns a list of progressively relaxed
filter dicts: level 0 = original, level N = drops the Nth-priority field.

Generalised from
``rede/backend/chatbot-service/app/services/filter_relaxation.py`` -- where
the ladder was hard-coded for real-estate (amenities -> price -> rooms ->
quartier -> property_type). Here it is driven by a domain-specific
``drop_priority`` list, with optional ``core_keys`` that are NEVER dropped.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def _clean(filters: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in filters.items() if not _is_empty(v)}


def build_relaxation_levels(
    filters: Dict[str, Any],
    drop_priority: Iterable[str],
    core_keys: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Return progressively relaxed filter dicts.

    Each successive level removes the next field listed in ``drop_priority``
    (if present in the previous level). Fields in ``core_keys`` are never
    removed. The final level always contains at least the core keys.

    Empty values (None, "", []) are stripped before computing levels.
    Levels that don't actually remove anything (because the field wasn't
    present) are skipped, so consecutive levels are always strictly different.
    """
    core: Set[str] = set(core_keys or set())
    cleaned = _clean(filters)

    levels: List[Dict[str, Any]] = [dict(cleaned)]
    if not cleaned:
        return levels

    current = dict(cleaned)
    for key in drop_priority:
        if key in core:
            continue
        if key not in current:
            continue
        current = {k: v for k, v in current.items() if k != key}
        if current != levels[-1]:
            levels.append(dict(current))

    if core:
        core_only = {k: v for k, v in cleaned.items() if k in core}
        if core_only and core_only != levels[-1]:
            levels.append(core_only)

    return levels
