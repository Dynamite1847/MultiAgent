"""Provider registry with base_url support for all providers."""
from .base import BaseProvider
from .google_provider import GoogleProvider
from .openai_provider import OpenAIProvider


def get_provider(provider_name: str, provider_config: dict) -> BaseProvider:
    api_key = provider_config.get("api_key", "")
    base_url = provider_config.get("base_url", "")

    if provider_name == "anthropic":
        return OpenAIProvider(
            api_key=api_key,
            base_url=base_url or "https://api.anthropic.com/v1"
        )
    elif provider_name == "google":
        return GoogleProvider(api_key=api_key, base_url=base_url)
    elif provider_name == "openai":
        return OpenAIProvider(
            api_key=api_key,
            base_url=base_url or "https://api.openai.com/v1"
        )
    elif provider_name == "doubao":
        return OpenAIProvider(
            api_key=api_key,
            base_url=base_url or "https://ark.cn-beijing.volces.com/api/v3"
        )
    elif provider_name == "dashscope":
        return OpenAIProvider(
            api_key=api_key,
            base_url=base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
    else:
        raise ValueError(f"Unknown provider: {provider_name}")
