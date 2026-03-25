"""Provider abstraction base class."""
from abc import ABC, abstractmethod
from typing import AsyncIterator, List, Any


class BaseProvider(ABC):
    """Unified interface for all LLM providers."""

    @abstractmethod
    async def stream_chat(
        self,
        messages: List[dict],
        system_prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
        top_p: float,
        **kwargs
    ) -> AsyncIterator[dict]:
        """
        Yields chunks: {"delta": str, "finish_reason": str|None, "usage": dict|None}
        usage is only set on the final chunk: {"prompt_tokens": int, "completion_tokens": int}
        """
        ...
