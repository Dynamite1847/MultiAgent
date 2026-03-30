"""
Tool Pipeline — 6 阶段工具执行管线。

1. renderToolCall — 通知前端将要执行什么
2. permissionCheck — 判断是否需要用户确认
3. preHook — 插件前置拦截（预留）
4. checkpoint — 破坏性操作前快照
5. executeTool — 调用实际工具
6. postHook — 插件后置钩子（预留）
"""
import asyncio
import os
import shutil
import time
from core.logger import logger
from tools.base import BaseTool
from tools.registry import ToolRegistry


class ToolPipeline:
    """6 阶段工具执行管线"""

    def __init__(self, tool_registry: ToolRegistry, project_root: str = "."):
        self.registry = tool_registry
        self.project_root = os.path.abspath(project_root)
        self.pre_hooks: list = []
        self.post_hooks: list = []

        # 用户确认机制
        self._permission_event = asyncio.Event()
        self._permission_result = True

    async def execute(self, tool_name: str, arguments: dict, on_event=None):
        """
        执行一次工具调用，经过 6 个阶段。

        Args:
            tool_name: 工具名称
            arguments: LLM 生成的参数
            on_event: 回调，用于发送 SSE 事件 (type, data)

        Returns:
            工具执行结果字符串
        """
        def emit(event_type, data):
            if on_event:
                on_event({"type": event_type, "data": data})

        start_time = time.time()

        # 1. renderToolCall
        emit("tool_start", {
            "name": tool_name,
            "arguments": arguments,
        })
        logger.info(f"Pipeline: 执行工具 {tool_name}")

        # 2. permissionCheck
        tool = self.registry.get(tool_name)
        if tool.permission == BaseTool.PERMISSION_CONFIRM:
            emit("tool_confirm", {
                "name": tool_name,
                "arguments": arguments,
                "message": f"Agent 想要执行 {tool_name}，是否允许？",
            })
            # 等待用户确认
            self._permission_event.clear()
            approved = await self._wait_for_permission(timeout=300)
            if not approved:
                result = f"用户拒绝了 {tool_name} 操作"
                emit("tool_rejected", {"name": tool_name})
                return result

        # 3. preHook
        for hook in self.pre_hooks:
            try:
                arguments = hook(tool_name, arguments) or arguments
            except Exception as e:
                logger.warning(f"preHook 失败: {e}")

        # 4. checkpoint（破坏性操作前快照）
        if tool.permission == BaseTool.PERMISSION_CONFIRM:
            self._create_checkpoint(tool_name, arguments)

        # 5. executeTool
        try:
            result = await asyncio.to_thread(self.registry.execute, tool_name, arguments)
            elapsed = time.time() - start_time
            emit("tool_result", {
                "name": tool_name,
                "result": result[:2000],  # 预览
                "elapsed": round(elapsed, 2),
            })
        except Exception as e:
            result = f"工具执行失败: {e}"
            emit("tool_error", {"name": tool_name, "error": str(e)})

        # 6. postHook
        for hook in self.post_hooks:
            try:
                hook(tool_name, arguments, result)
            except Exception as e:
                logger.warning(f"postHook 失败: {e}")

        return result

    async def _wait_for_permission(self, timeout: float = 300) -> bool:
        """等待用户确认，超时自动拒绝"""
        try:
            await asyncio.wait_for(self._permission_event.wait(), timeout=timeout)
            return self._permission_result
        except asyncio.TimeoutError:
            logger.warning("用户确认超时，自动拒绝")
            return False

    def grant_permission(self, approved: bool = True):
        """前端调用：用户批准或拒绝"""
        self._permission_result = approved
        self._permission_event.set()

    def _create_checkpoint(self, tool_name: str, arguments: dict):
        """在执行破坏性操作前创建文件快照"""
        if tool_name == "write_file":
            path = arguments.get("path", "")
            abs_path = os.path.normpath(os.path.join(self.project_root, path))
            if os.path.exists(abs_path):
                checkpoint_dir = os.path.join(self.project_root, ".checkpoints")
                os.makedirs(checkpoint_dir, exist_ok=True)
                backup_name = f"{os.path.basename(path)}.{int(time.time())}.bak"
                backup_path = os.path.join(checkpoint_dir, backup_name)
                shutil.copy2(abs_path, backup_path)
                logger.debug(f"Checkpoint: {path} → {backup_name}")
