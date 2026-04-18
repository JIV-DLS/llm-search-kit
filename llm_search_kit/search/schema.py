"""Schema describing the searchable fields for a given domain.

A ``SearchSchema`` declares:
  * the list of fields the LLM is allowed to populate;
  * for each field its type, optional enum, optional description;
  * the drop priority (which filters to relax first when no results);
  * the core keys (filters that must NEVER be dropped).

The ``SearchCatalogSkill`` uses this to (1) auto-build the OpenAI tool
parameters schema and (2) drive ``build_relaxation_levels``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class SearchField:
    """A single searchable field.

    ``json_type`` follows JSON Schema names: ``string``, ``number``,
    ``integer``, ``boolean``, ``array``.  For arrays use ``item_type``.
    """

    name: str
    json_type: str = "string"
    description: str = ""
    enum: Optional[List[Any]] = None
    item_type: Optional[str] = None  # only meaningful when json_type == "array"

    def to_json_schema(self) -> Dict[str, Any]:
        prop: Dict[str, Any] = {"type": self.json_type}
        if self.description:
            prop["description"] = self.description
        if self.enum:
            prop["enum"] = list(self.enum)
        if self.json_type == "array":
            prop["items"] = {"type": self.item_type or "string"}
        return prop


@dataclass
class SearchSchema:
    """Full schema describing one domain's search surface."""

    fields: List[SearchField]
    drop_priority: List[str] = field(default_factory=list)
    core_keys: Set[str] = field(default_factory=set)
    required: List[str] = field(default_factory=list)
    extra_properties: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        names = {f.name for f in self.fields}
        for k in self.core_keys:
            if k not in names and k not in self.extra_properties:
                raise ValueError(
                    f"core_keys references unknown field '{k}'. "
                    f"Known fields: {sorted(names)}"
                )
        for k in self.drop_priority:
            if k not in names and k not in self.extra_properties:
                raise ValueError(
                    f"drop_priority references unknown field '{k}'. "
                    f"Known fields: {sorted(names)}"
                )

    def to_openai_parameters(self) -> Dict[str, Any]:
        """Build the JSON Schema accepted by OpenAI tool-calling."""
        properties: Dict[str, Any] = {}
        for f in self.fields:
            properties[f.name] = f.to_json_schema()
        for name, prop in self.extra_properties.items():
            properties[name] = prop
        return {
            "type": "object",
            "properties": properties,
            "required": list(self.required),
        }

    def field_names(self) -> List[str]:
        return [f.name for f in self.fields]
