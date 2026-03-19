"""
WritingAgent - 文档撰写Agent
"""
from agents.base import BaseAgent
from core.logger import logger


class WritingAgent(BaseAgent):
    """文档撰写Agent：纯LLM生成，自动选择文档结构"""

    def execute(self, input_data: dict, context: str = "") -> str:
        doc_requirement = input_data.get("doc_requirement", input_data.get("requirement", "生成文档"))
        content = input_data.get("content", "")

        logger.info(f"WritingAgent 开始执行")
        logger.debug(f"文档要求: {doc_requirement}", indent=1)

        prompt = f"""请根据以下要求和素材，撰写一份完整的文档。

## 文档要求
{doc_requirement}

## 可用素材
{content if content else "(请参考上下文中前序步骤的输出作为素材)"}

请：
1. 根据需求自动选择合适的文档类型和结构
2. 生成完整的、可直接使用的文档
3. 使用 Markdown 格式
4. 确保内容完整、逻辑连贯、专业正式
"""

        messages = self._build_messages(prompt, context)
        result = self.llm_client.call(messages, role=self.name)

        logger.info(f"WritingAgent 完成")
        return result
