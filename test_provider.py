import sys
import asyncio

sys.path.append('.')
from services.provider_config import get_provider_config
from openai import AsyncOpenAI

async def test():
    cfg = get_provider_config('anthropic1')
    model = cfg['models'][0]
    print(f"Requesting to: {cfg.get('base_url')} with model: {model}...")
    
    client = AsyncOpenAI(
        api_key=cfg['api_key'],
        base_url=cfg['base_url']
    )
    
    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=[{'role': 'user', 'content': 'Say exactly "Test ok".'}],
            stream=True,
            max_tokens=20
        )
        print("Stream established, reading chunks...")
        async for chunk in stream:
            print(f"RAW CHUNK: {chunk}")
        print('\n--- SUCCESS ---')
    except Exception as e:
        print(f"\n--- FAILED ---\nError: {e}")

if __name__ == "__main__":
    asyncio.run(test())
