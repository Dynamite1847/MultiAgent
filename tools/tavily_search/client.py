"""
Tavily 搜索工具 - 封装 Tavily Python SDK
"""
from tavily import TavilyClient
from core.logger import logger


class TavilySearchTool:
    """Tavily 搜索工具"""

    def __init__(self, config):
        self.api_key = config.tavily_api_key
        self.client = TavilyClient(api_key=self.api_key)

    def search(
        self,
        query: str,
        search_depth: str = "basic",
        max_results: int = 10,
    ) -> list[dict]:
        """
        执行搜索
        
        Args:
            query: 搜索查询
            search_depth: "basic" 或 "advanced"
            max_results: 最大结果数
        
        Returns:
            搜索结果列表 [{title, url, content, score}]
        """
        logger.debug(f"Tavily搜索: \"{query}\" (depth={search_depth})", indent=1)

        try:
            response = self.client.search(
                query=query,
                search_depth=search_depth,
                max_results=max_results,
            )
            results = response.get("results", [])
            logger.debug(f"└─ 返回{len(results)}条结果", indent=1)

            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                    "score": r.get("score", 0),
                }
                for r in results
            ]
        except Exception as e:
            logger.error(f"Tavily搜索失败: {e}")
            raise

    def search_batch(
        self,
        queries: list[str],
        search_depth: str = "basic",
        max_results: int = 10,
    ) -> dict[str, list[dict]]:
        """
        批量搜索
        
        Returns:
            {query: [results]}
        """
        all_results = {}
        for query in queries:
            all_results[query] = self.search(
                query=query,
                search_depth=search_depth,
                max_results=max_results,
            )
        return all_results
