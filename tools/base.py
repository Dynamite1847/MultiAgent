"""
Tool 基类 — 所有工具的统一接口。

Tool 是 Agent 的"手脚"：
- Agent（LLM）通过 Function Calling 决定调用哪个 Tool，生成参数
- Runtime 执行 Tool，返回结果给 Agent

每个 Tool 只做一件事，不包含 LLM 逻辑。
"""
from abc import ABC, abstractmethod


class BaseTool(ABC):
    """工具基类"""

    # 子类必须定义
    name: str = ""                  # 工具名（function name）
    description: str = ""           # 给 LLM 看的描述
    parameters: dict = {}           # JSON Schema 格式的参数定义

    # 权限级别
    PERMISSION_AUTO = "auto"        # 自动执行（搜索、读取）
    PERMISSION_CONFIRM = "confirm"  # 需要用户确认（写入、删除）
    permission: str = PERMISSION_AUTO

    @abstractmethod
    def execute(self, **params) -> str:
        """
        执行工具。

        Args:
            **params: 由 LLM 生成的参数（已从 JSON 解析）

        Returns:
            执行结果字符串，会被送回给 LLM 作为 tool_result
        """
        raise NotImplementedError

    def get_openai_definition(self) -> dict:
        """生成 OpenAI Function Calling 格式的工具定义"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": [
                        k for k, v in self.parameters.items()
                        if v.get("required", False)
                    ],
                },
            },
        }

    def __repr__(self):
        return f"<Tool:{self.name}>"
