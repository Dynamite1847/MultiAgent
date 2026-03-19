"""
AnalysisAgent - 分析整合Agent
"""
from agents.base import BaseAgent
from core.logger import logger


class AnalysisAgent(BaseAgent):
    """分析整合Agent：纯LLM推理，自动选择分析框架"""

    def execute(self, input_data: dict, context: str = "") -> str:
        requirement = input_data.get("requirement", "进行综合分析")
        content = input_data.get("content", "")

        logger.info(f"AnalysisAgent 开始执行")
        logger.debug(f"分析要求: {requirement}", indent=1)

        prompt = f"""请对以下内容进行深度分析。

## 分析要求
{requirement}

## 待分析内容
{content if content else "(请参考上下文中前序步骤的输出)"}

请：
1. 首先说明你选择的分析方法及原因
2. 给出系统性的分析结论
3. 提炼核心洞察
4. 给出建议
"""

        messages = self._build_messages(prompt, context)
        result = self.llm_client.call(messages, role=self.name)

        logger.info(f"AnalysisAgent 完成")
        return result
