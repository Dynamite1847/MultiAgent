"""
API 验证脚本 - 逐个测试所有 Provider 的 API 连通性
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openai import OpenAI
from rich.console import Console
from rich.table import Table
from core.config import Config

console = Console()


def test_provider(name: str, base_url: str, api_key: str, model: str) -> dict:
    """测试单个 Provider 的 API"""
    result = {
        "provider": name,
        "model": model,
        "status": "❌ 失败",
        "latency": "-",
        "response": "",
        "error": "",
    }

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)

        start = time.time()
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "请用一句话介绍你自己。"}],
            max_tokens=100,
            temperature=0.7,
        )
        elapsed = time.time() - start

        content = response.choices[0].message.content or ""
        tokens = 0
        if response.usage:
            tokens = (response.usage.prompt_tokens or 0) + (response.usage.completion_tokens or 0)

        result["status"] = "✅ 成功"
        result["latency"] = f"{elapsed:.1f}s"
        result["response"] = content[:80] + ("..." if len(content) > 80 else "")
        result["tokens"] = str(tokens)

    except Exception as e:
        result["error"] = str(e)[:120]

    return result


def test_tavily() -> dict:
    """测试 Tavily API"""
    result = {
        "provider": "tavily",
        "model": "search",
        "status": "❌ 失败",
        "latency": "-",
        "response": "",
        "error": "",
    }

    try:
        from tavily import TavilyClient

        api_key = os.getenv("TAVILY_API_KEY", "")
        if not api_key or api_key == "tvly-xxx":
            result["error"] = "TAVILY_API_KEY 未设置或为占位值"
            return result

        client = TavilyClient(api_key=api_key)

        start = time.time()
        response = client.search(query="test", max_results=1, search_depth="basic")
        elapsed = time.time() - start

        results = response.get("results", [])
        result["status"] = "✅ 成功"
        result["latency"] = f"{elapsed:.1f}s"
        result["response"] = f"返回 {len(results)} 条结果"
        result["tokens"] = "-"

    except Exception as e:
        result["error"] = str(e)[:120]

    return result


def main():
    console.print("\n[bold cyan]🔍 API 连通性验证[/bold cyan]\n")

    config = Config()
    results = []

    # 测试所有 LLM Provider
    for provider_name, provider_info in config.providers.items():
        base_url = provider_info["base_url"]
        api_key_env = provider_info.get("api_key_env", f"{provider_name.upper()}_API_KEY")
        api_key = os.getenv(api_key_env, "")
        models = provider_info.get("models", [])

        if not api_key:
            results.append({
                "provider": provider_name,
                "model": ", ".join(models),
                "status": "⚠️ 跳过",
                "latency": "-",
                "response": "",
                "error": f"环境变量 {api_key_env} 未设置",
                "tokens": "-",
            })
            continue

        for model in models:
            console.print(f"  测试 [bold]{provider_name}/{model}[/bold] ...", end=" ")
            r = test_provider(provider_name, base_url, api_key, model)
            console.print(r["status"])
            if r.get("error"):
                console.print(f"    [red]{r['error']}[/red]")
            results.append(r)

    # 测试 Tavily
    console.print(f"  测试 [bold]tavily/search[/bold] ...", end=" ")
    tavily_result = test_tavily()
    console.print(tavily_result["status"])
    if tavily_result.get("error"):
        console.print(f"    [red]{tavily_result['error']}[/red]")
    results.append(tavily_result)

    # 汇总表格
    console.print()
    table = Table(title="API 验证结果", show_lines=True)
    table.add_column("Provider", style="cyan", width=12)
    table.add_column("Model", style="white", width=30)
    table.add_column("状态", width=8)
    table.add_column("延迟", width=8)
    table.add_column("响应 / 错误", style="dim", max_width=60)

    for r in results:
        display = r.get("response") or r.get("error", "")
        table.add_row(
            r["provider"],
            r["model"],
            r["status"],
            r["latency"],
            display,
        )

    console.print(table)

    # 统计
    success = sum(1 for r in results if "成功" in r["status"])
    total = len(results)
    console.print(f"\n[bold]结果: {success}/{total} 通过[/bold]\n")


if __name__ == "__main__":
    main()
