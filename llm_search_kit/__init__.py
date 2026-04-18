"""llm-search-kit: domain-agnostic agentic LLM search."""
from .agent import AgentEngine, BaseSkill, SkillRegistry, SkillResult
from .llm import BaseLLMClient, OpenAILLMClient, ResilientLLMClient
from .search import (
    CatalogBackend,
    SearchCatalogSkill,
    SearchField,
    SearchSchema,
    build_relaxation_levels,
)

__version__ = "0.1.0"

__all__ = [
    "AgentEngine",
    "BaseLLMClient",
    "BaseSkill",
    "CatalogBackend",
    "OpenAILLMClient",
    "ResilientLLMClient",
    "SearchCatalogSkill",
    "SearchField",
    "SearchSchema",
    "SkillRegistry",
    "SkillResult",
    "build_relaxation_levels",
    "__version__",
]
