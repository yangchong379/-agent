from typing import Protocol, TypeVar

from pydantic import BaseModel


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LLMError(RuntimeError):
    """Raised when a model call cannot produce a validated result."""


class StructuredLLM(Protocol):
    def parse(
        self,
        *,
        system_prompt: str,
        user_content: str,
        schema: type[SchemaT],
    ) -> SchemaT: ...

