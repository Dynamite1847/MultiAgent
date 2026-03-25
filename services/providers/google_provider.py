"""Unified OpenAI-compatible provider for Google Gemini (via proxy)."""
import json
import logging
from openai import AsyncOpenAI
from typing import AsyncIterator, List
from .base import BaseProvider

logger = logging.getLogger(__name__)


class GoogleProvider(BaseProvider):
    def __init__(self, api_key: str, base_url: str):
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=300.0,  # 5 min timeout for large payloads
        )

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
        all_messages = []
        if system_prompt:
            all_messages.append({"role": "system", "content": system_prompt})
        all_messages.extend(messages)

        # Log payload size for diagnostics
        payload_json = json.dumps(all_messages, ensure_ascii=False)
        payload_kb = len(payload_json.encode("utf-8")) / 1024
        logger.info(f"[Google] Calling model={model}, messages_count={len(all_messages)}, payload_size={payload_kb:.1f}KB")

        usage_data = None
        stream = await self.client.chat.completions.create(
            model=model,
            messages=all_messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stream=True,
        )
        async for chunk in stream:
            delta = ""
            finish_reason = None
            if chunk.choices:
                choice = chunk.choices[0]
                if choice.delta and choice.delta.content:
                    delta = choice.delta.content
                finish_reason = choice.finish_reason
            if hasattr(chunk, "usage") and chunk.usage:
                usage_data = {
                    "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(chunk.usage, "completion_tokens", 0)
                }
            if delta:
                yield {"delta": delta, "finish_reason": finish_reason, "usage": None}

        yield {"delta": "", "finish_reason": "stop", "usage": usage_data}
