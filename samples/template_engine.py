"""Base prompt template class for structured LLM interactions.

All prompt templates extend this base class, enforcing a consistent contract
across the application. This makes prompt engineering testable, versionable,
and maintainable as the system scales.
"""
from abc import ABC, abstractmethod
from typing import Any


class PromptTemplate(ABC):
    """Base class for all prompt templates.

    Each template defines:
    - System and user prompts (what the model sees)
    - Tool name, description, and output schema (for function calling)
    - Input/output validation hooks (for quality assurance)
    - Version and model preference (for tracking and A/B testing)
    """

    version: str = "1.0.0"
    model: str = "sonnet"        # Default model tier
    temperature: float = 0.2
    max_tokens: int = 4096

    @abstractmethod
    def build_system_prompt(self) -> str:
        """Build the system prompt."""
        ...

    @abstractmethod
    def build_user_prompt(self, **data: Any) -> str:
        """Build the user prompt from input data."""
        ...

    @abstractmethod
    def get_tool_name(self) -> str:
        """Return the tool/function name for function calling."""
        ...

    @abstractmethod
    def get_tool_description(self) -> str:
        """Return description of what the tool does."""
        ...

    @abstractmethod
    def get_output_schema(self) -> dict:
        """Return the JSON schema for function calling output."""
        ...

    def validate_input(self, **data: Any) -> list[str]:
        """Validate input data, return list of warnings (empty = valid)."""
        return []

    def validate_output(self, result: dict) -> None:
        """Validate LLM output. Raise ValueError if invalid."""
        pass
