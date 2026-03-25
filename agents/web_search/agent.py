"""
WebSearchAgent - 网络搜索Agent
"""
from agents.base import BaseAgent
from core.logger import logger


class WebSearchAgent(BaseAgent):
    """网络搜索Agent：调用Tavily搜索，LLM提炼关键信息"""

    def execute(self, input_data: dict, context: str = "") -> str:
        queries = input_data.get("queries", [])
        search_depth = input_data.get("search_depth", "advanced")
        max_results = input_data.get("max_results", 10)

        if not queries:
            return "错误：未提供搜索查询（input 缺少 queries 字段）"

        logger.info(f"WebSearchAgent 开始执行 ({len(queries)} 个查询, depth={search_depth}, max={max_results})")

        # 1. 调用 Tavily 搜索
        tavily = self.tool_registry.get_tool("tavily_search")
        all_results = {}

        for query in queries:
            logger.debug(f"调用工具: tavily_search", indent=1)
            results = tavily.search(
                query=query,
                search_depth=search_depth,
                max_results=max_results,
            )
            all_results[query] = results

        # 2. 用 LLM 提炼关键信息
        search_text = self._format_search_results(all_results)

        prompt = f"""以下是搜索结果，请整理并提炼关键信息：

{search_text}

请用结构化的 Markdown 格式输出：
1. 每个查询的核心发现
2. 关键事实和数据
3. 信息来源链接
4. 信息时效性评估
"""

        messages = self._build_messages(prompt, context)
        result = self.llm_client.call(messages, role=self.name)

        logger.info(f"WebSearchAgent 完成")
        return result

    def _format_search_results(self, all_results: dict) -> str:
        """格式化搜索结果为文本"""
        parts = []
        for query, results in all_results.items():
            parts.append(f"### 查询: {query}\n")
            for i, r in enumerate(results, 1):
                parts.append(f"**{i}. {r['title']}**")
                parts.append(f"URL: {r['url']}")
                parts.append(f"摘要: {r['content']}\n")
        return "\n".join(parts)
