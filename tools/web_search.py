"""
Web Search Tool — 搜索互联网获取最新信息。

降级自 agents/web_search/agent.py：
- 去掉了 LLM "提炼" 环节（现在由 Agent Core 自己决定如何处理搜索结果）
- 只做"搜索 → 格式化结果"，纯粹的执行层
"""
from tools.base import BaseTool
from core.logger import logger


class WebSearchTool(BaseTool):
    """互联网搜索工具"""

    name = "web_search"
    description = "搜索互联网获取最新信息。返回多条搜索结果，每条包含标题、URL 和内容摘要。"
    permission = BaseTool.PERMISSION_AUTO

    parameters = {
        "queries": {
            "type": "array",
            "items": {"type": "string"},
            "description": "搜索关键词列表。每个关键词会独立搜索。",
            "required": True,
        },
        "search_depth": {
            "type": "string",
            "enum": ["basic", "advanced"],
            "description": "搜索深度。advanced 更慢但结果更全面。",
            "default": "basic",
        },
        "max_results": {
            "type": "integer",
            "description": "每个关键词返回的最大结果数。",
            "default": 15,
        },
    }

    def __init__(self, tavily_client):
        """
        Args:
            tavily_client: TavilySearchTool 实例（复用已有的 Tavily 封装）
        """
        self._tavily = tavily_client

    def execute(self, queries: list[str], search_depth: str = "basic", max_results: int = 15) -> str:
        if not queries:
            return "错误：请提供至少一个搜索关键词"

        logger.info(f"WebSearchTool: {len(queries)} 个查询, depth={search_depth}")

        parts = []
        for query in queries:
            try:
                results = self._tavily.search(
                    query=query,
                    search_depth=search_depth,
                    max_results=max_results,
                )
                parts.append(f"### 搜索: {query}\n")
                if not results:
                    parts.append("未找到相关结果。\n")
                    continue
                for i, r in enumerate(results, 1):
                    parts.append(f"**{i}. {r['title']}**")
                    parts.append(f"URL: {r['url']}")
                    parts.append(f"摘要: {r['content']}\n")
            except Exception as e:
                parts.append(f"### 搜索: {query}\n搜索失败: {e}\n")

        return "\n".join(parts)
