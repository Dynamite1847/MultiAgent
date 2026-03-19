"""
BaseAgent - 所有子Agent的抽象基类
"""
from abc import ABC, abstractmethod
from core.logger import logger


class BaseAgent(ABC):
    """子Agent抽象基类"""

    def __init__(self, config, llm_client, tool_registry, system_prompt: str, manifest: dict):
        self.config = config
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.system_prompt = system_prompt
        self.manifest = manifest
        self.name = manifest.get("name", "unknown")
        self.display_name = manifest.get("display_name", self.name)

    @abstractmethod
    def execute(self, input_data: dict, context: str = "") -> str:
        """
        执行任务
        
        Args:
            input_data: 任务输入（按 manifest 中的 input_schema）
            context: 上下文信息（前序步骤的输出）
        
        Returns:
            执行结果（字符串）
        """
        pass

    def _build_messages(self, user_prompt: str, context: str = "") -> list[dict]:
        """构建 LLM 消息列表"""
        messages = []

        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

        if context:
            messages.append({
                "role": "user",
                "content": f"## 前序步骤的上下文信息\n\n{context}",
            })

        messages.append({"role": "user", "content": user_prompt})

        return messages

    def __repr__(self):
        return f"<{self.__class__.__name__} name={self.name}>"
