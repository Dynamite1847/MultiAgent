"""OpenAI-compatible provider (also used as fallback)."""
import json
import logging
from openai import AsyncOpenAI
from typing import AsyncIterator, List
from .base import BaseProvider

logger = logging.getLogger(__name__)


class OpenAIProvider(BaseProvider):
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=1200.0,  # 20 min timeout for large payloads and thinking models
            max_retries=0,   # Prevent double-spending and background retries
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
        logger.info(f"[OpenAI] Calling model={model}, messages_count={len(all_messages)}, payload_size={payload_kb:.1f}KB")

        # LinkAPI supports extended output for Claude models (e.g. 8k, 32k), 
        # but fails silently with 0 chunks if given excessively large values like 100,000.
        # Cap to a verified safe maximum (32768) to prevent connection drops while 
        # allowing maximum extended output.
        if "claude" in model.lower():
            max_tokens = min(max_tokens, 32768)
        
        # DashScope (Alibaba Cloud) models have varying limits (glm-5: 32768, others: 98304)
        # Use the lowest common denominator to avoid 400 errors
        if "dashscope" in str(self.client.base_url):
            max_tokens = min(max_tokens, 32768)
                
        completion_kwargs = {
            "model": model,
            "messages": all_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "frequency_penalty": kwargs.get("frequency_penalty", 0.0),
            "stream": True,
        }

        # Build extra_body: start with caller-provided, then layer on provider-specific
        extra_body = dict(kwargs.get("extra_body") or {})

        # Volcengine/Doubao specific: enable thinking by default
        if "ark.cn-beijing.volces.com" in str(self.client.base_url):
            extra_body.setdefault("thinking", {"type": "enabled"})

        if extra_body:
            completion_kwargs["extra_body"] = extra_body

        stream = await self.client.chat.completions.create(**completion_kwargs)
        is_thinking = False
        has_finished_thinking = False
        usage_data = None

        async for chunk in stream:
            delta = ""
            finish_reason = None
            if chunk.choices:
                choice = chunk.choices[0]
                reasoning = getattr(choice.delta, "reasoning_content", None)
                content = getattr(choice.delta, "content", None)

                if reasoning:
                    if not is_thinking:
                        delta += "💡 **深度思考过程：**\n```thinking\n"
                        is_thinking = True
                    delta += reasoning
                
                if content:
                    if is_thinking and not has_finished_thinking:
                        delta += "\n```\n\n"
                        has_finished_thinking = True
                    delta += content

                finish_reason = choice.finish_reason
            if hasattr(chunk, "usage") and chunk.usage:
                usage_data = {
                    "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(chunk.usage, "completion_tokens", 0)
                }
            if delta:
                yield {"delta": delta, "finish_reason": finish_reason, "usage": None}

        yield {"delta": "", "finish_reason": "stop", "usage": usage_data}
