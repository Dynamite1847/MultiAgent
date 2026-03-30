"""
Tool Registry — 统一的工具注册中心。

职责：
- 扫描并注册所有 Tool
- 生成 OpenAI Function Calling 格式的 tools 数组
- 根据 tool name 执行对应工具
"""
import os
import json
from core.logger import logger
from tools.base import BaseTool


class ToolRegistry:
    """工具注册中心"""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        """注册一个工具"""
        if not tool.name:
            raise ValueError(f"Tool {tool.__class__.__name__} 缺少 name 属性")
        self._tools[tool.name] = tool
        logger.debug(f"├─ 注册工具: {tool.name} ({tool.permission})")

    def register_all(self, tools: list[BaseTool]):
        """批量注册"""
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> BaseTool:
        """获取工具实例"""
        if name not in self._tools:
            raise KeyError(f"工具未注册: {name}")
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def get_openai_definitions(self) -> list[dict]:
        """生成 OpenAI Function Calling 格式的 tools 数组"""
        return [tool.get_openai_definition() for tool in self._tools.values()]

    def execute(self, name: str, arguments: dict) -> str:
        """执行指定工具"""
        tool = self.get(name)
        try:
            result = tool.execute(**arguments)
            logger.debug(f"工具执行完成: {name} → {len(str(result))} 字符")
            return result
        except Exception as e:
            error_msg = f"工具 {name} 执行失败: {e}"
            logger.error(error_msg)
            return error_msg

    def get_permission(self, name: str) -> str:
        """获取工具的权限级别"""
        tool = self.get(name)
        return tool.permission
