"""
Agent Loop — 核心 Agent 循环。

骨架是一个有上限的 while 循环（最大 25 次迭代），每次迭代对应一轮模型调用。

每次迭代的流程：
1. 检查是否需要 compact
2. 构建完整 prompt（Instructions + Memory + Skills + Messages）
3. 发起流式请求（带 tools 定义）
4. 实时处理事件流
5. 检查 stop_reason — tool_use 则执行工具，end_turn 或 max_tokens 则结束
6. 构建 tool_result message，追加到 messages 数组，进入下一轮
"""
import asyncio
import json
import time
import uuid
from typing import AsyncGenerator
from core.logger import logger
from core.llm_client import LLMClient
from agent.state import AgentState
from agent.tool_pipeline import ToolPipeline
from tools.registry import ToolRegistry


MAX_TURNS = 25
COMPACT_THRESHOLD = 0.85


class AgentLoop:
    """核心 Agent 循环"""

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        tool_pipeline: ToolPipeline,
        instructions: str = "",
        context_limit: int = 128000,
    ):
        self.llm = llm_client
        self.tools = tool_registry
        self.pipeline = tool_pipeline
        self.instructions = instructions
        self.context_limit = context_limit

        # 运行时状态
        self.state: AgentState | None = None
        self._cancelled = False
        self._interrupted_messages: list[dict] = []  # 用户中途注入的消息

    async def run(
        self,
        user_message: str,
        state: AgentState | None = None,
        role: str = "orchestrator",
    ) -> AsyncGenerator[dict, None]:
        """
        主循环 — 在一个 SSE 流内持续运行。
        yield SSE 事件给前端实时展示。

        Args:
            user_message: 用户输入
            state: 恢复的 AgentState，None 则新建
            role: LLM 角色（用于查找模型配置）
        """
        # 初始化或恢复状态
        if state:
            self.state = state
        else:
            self.state = AgentState()

        self.state.add_user_message(user_message)
        self.state.status = "thinking"
        self._cancelled = False
        self._interrupted_messages = []

        start_time = time.time()
        self.llm.reset_task_stats()

        logger.section(f"Agent Loop 开始 [session={self.state.session_id or 'default'}]")
        logger.info(f"用户输入: {user_message[:200]}{'...' if len(user_message) > 200 else ''}")
        logger.info(f"可用工具: {self.tools.list_tools()}")
        logger.info(f"上下文限制: {self.context_limit} tokens")

        yield {"type": "agent_start", "data": {
            "message": user_message,
            "max_turns": MAX_TURNS,
        }}

        # ═══ Agent Loop ═══
        for turn in range(MAX_TURNS):
            if self._cancelled:
                self.state.status = "idle"
                yield {"type": "interrupted", "data": {"turn": turn, "reason": "cancelled"}}
                return

            # ① 检查是否需要 compact
            est_tokens = self.state.estimate_tokens()
            if self.state.is_over_limit(self.context_limit, COMPACT_THRESHOLD):
                logger.warning(f"R{turn+1} 上下文接近上限 ({est_tokens}/{self.context_limit})，触发 compact")
                yield {"type": "compact", "data": {"message": "上下文接近容量上限，正在压缩..."}}
                await self._compact_messages(role)
                yield {"type": "compact_done", "data": {
                    "tokens_after": self.state.estimate_tokens()
                }}

            # 注入用户中途消息
            if self._interrupted_messages:
                for msg in self._interrupted_messages:
                    self.state.messages.append(msg)
                self._interrupted_messages = []

            # ② 构建完整 prompt
            system_prompt = self._build_system_prompt()
            tool_defs = self.tools.get_openai_definitions()

            # ③ 发起请求
            self.state.turn_count = turn + 1
            self.state.status = "thinking"

            logger.info(f"── R{turn+1} 开始 ({len(self.state.messages)} 条消息, ~{self.state.estimate_tokens()} tokens) ──")

            yield {"type": "thinking", "data": {
                "turn": turn + 1,
                "message": f"思考中（第 {turn + 1} 轮）...",
                "tokens": self.state.estimate_tokens(),
            }}

            # 构建 messages（system prompt + 对话历史）
            full_messages = [{"role": "system", "content": system_prompt}] + self.state.messages

            try:
                llm_start = time.time()
                response = self.llm.call_with_tools(
                    messages=full_messages,
                    tools=tool_defs,
                    role=role,
                )
                llm_elapsed = round(time.time() - llm_start, 1)
            except Exception as e:
                logger.error(f"R{turn+1} LLM 调用失败: {e}")
                yield {"type": "error", "data": {"message": f"LLM 调用失败: {e}", "turn": turn + 1}}
                self.state.status = "idle"
                return

            # ④ 处理响应
            content = response.get("content", "")
            tool_calls = response.get("tool_calls", [])
            usage = response.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = usage.get("total_tokens", 0)
            self.state.total_tokens += total_tokens
            stop_reason = response.get("stop_reason", "unknown")

            logger.info(f"R{turn+1} LLM 响应: stop={stop_reason}, "
                       f"content={len(content)}字符, tools={len(tool_calls)}, "
                       f"tokens={prompt_tokens}+{completion_tokens}={total_tokens}, "
                       f"耗时={llm_elapsed}s")
            if content:
                logger.debug(f"R{turn+1} 回复预览: {content[:150]}{'...' if len(content) > 150 else ''}")

            # ⑤ 检查 stop_reason
            if not tool_calls:
                # end_turn 或 max_tokens → 循环结束
                self.state.add_assistant_message(content)
                self.state.status = "done"

                if content:
                    yield {"type": "text", "data": {"content": content, "turn": turn + 1}}

                elapsed = time.time() - start_time
                stats = self.llm.get_task_stats()
                logger.info(f"Agent Loop 完成: {turn+1} 轮, {round(elapsed, 1)}s, "
                           f"总 token: {self.state.total_tokens}, "
                           f"工具调用: {self.state.total_tool_calls} 次")
                yield {"type": "done", "data": {
                    "turns": turn + 1,
                    "elapsed": round(elapsed, 1),
                    "stats": stats,
                }}
                return

            # ── 有 tool_calls: 执行工具 ──
            if content:
                yield {"type": "text", "data": {"content": content, "turn": turn + 1}}

            # 记录 assistant message（含 tool_calls）
            assistant_tc = [
                {
                    "id": tc.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"], ensure_ascii=False)
                            if isinstance(tc["arguments"], dict)
                            else tc["arguments"],
                    },
                }
                for tc in tool_calls
            ]
            self.state.add_assistant_message(content or "", assistant_tc)

            # ⑥ 通过 Pipeline 执行每个 tool call
            self.state.status = "executing"
            events_buffer = []

            def collect_event(evt):
                events_buffer.append(evt)

            for tc in tool_calls:
                tc_id = tc.get("id", f"call_{uuid.uuid4().hex[:8]}")
                tc_name = tc["name"]
                tc_args = tc["arguments"] if isinstance(tc["arguments"], dict) else json.loads(tc["arguments"])

                self.state.total_tool_calls += 1

                # 详细日志
                args_preview = json.dumps(tc_args, ensure_ascii=False)
                if len(args_preview) > 200:
                    args_preview = args_preview[:200] + '...'
                logger.info(f"R{turn+1} 调用工具: {tc_name}({args_preview})")

                yield {"type": "tool_call", "data": {
                    "id": tc_id,
                    "name": tc_name,
                    "arguments": tc_args,
                    "turn": turn + 1,
                }}

                # 通过 pipeline 执行（含 permissionCheck, checkpoint 等）
                tool_start = time.time()
                result = await self.pipeline.execute(tc_name, tc_args, on_event=collect_event)
                tool_elapsed = round(time.time() - tool_start, 2)

                # flush pipeline events
                for evt in events_buffer:
                    yield evt
                events_buffer.clear()

                # 记录 tool result
                self.state.add_tool_result(tc_id, result)

                logger.info(f"R{turn+1} 工具结果: {tc_name} → {len(result)}字符, 耗时={tool_elapsed}s")
                if len(result) < 500:
                    logger.debug(f"R{turn+1} 工具输出: {result[:300]}")

                yield {"type": "tool_result", "data": {
                    "id": tc_id,
                    "name": tc_name,
                    "result": result[:2000],
                    "elapsed": tool_elapsed,
                    "turn": turn + 1,
                }}

            # 进入下一轮

        # ── 安全阀：达到上限 ──
        self.state.status = "done"
        elapsed = time.time() - start_time
        yield {"type": "max_turns", "data": {
            "message": f"已达到最大执行轮次 ({MAX_TURNS})",
            "turns": MAX_TURNS,
            "elapsed": round(elapsed, 1),
        }}

    def interrupt(self, user_feedback: str):
        """
        用户打断 — 将反馈注入到下一轮的 messages 中。
        当前轮不受影响，下一轮 LLM 会看到用户补充。
        """
        self._interrupted_messages.append({
            "role": "user",
            "content": user_feedback,
        })
        logger.info(f"用户注入反馈: {user_feedback[:100]}...")

    def cancel(self):
        """取消执行"""
        self._cancelled = True
        self.llm.cancel()
        logger.info("Agent Loop 被取消")

    def _build_system_prompt(self) -> str:
        """构建系统 prompt"""
        parts = []

        # Instructions
        if self.instructions:
            parts.append(self.instructions)

        # 时间
        from datetime import datetime
        parts.append(f"\n## 当前时间\n{datetime.now().strftime('%Y-%m-%d %H:%M (%A)')}")

        return "\n\n".join(parts)

    async def _compact_messages(self, role: str = "orchestrator"):
        """
        Auto-compact：压缩消息。
        发起独立 API 调用生成摘要，替换 messages 数组。
        """
        logger.info(f"Auto-compact 触发 (估计 {self.state.estimate_tokens()} tokens)")

        # 构建摘要请求
        msg_text = []
        for m in self.state.messages:
            r = m.get("role", "?")
            c = m.get("content", "")
            if r == "tool":
                c = c[:500]  # tool result 截断
            msg_text.append(f"[{r}] {c}")

        summary_prompt = (
            "请将以下对话历史压缩为要点摘要。保留：\n"
            "1. 用户的核心需求和偏好\n"
            "2. 重要的决策和结论\n"
            "3. 工具调用的关键结果（不要保留完整的搜索结果，只保留发现要点）\n"
            "4. 当前正在进行的任务状态\n\n"
            "--- 对话历史 ---\n\n"
            + "\n\n".join(msg_text[-50:])  # 最近 50 条
        )

        try:
            summary = self.llm.call(
                [{"role": "user", "content": summary_prompt}],
                role=role,
                temperature=0.3,
            )

            # 替换 messages
            self.state.messages = [
                {"role": "user", "content": f"[对话历史摘要]\n\n{summary}"},
                {"role": "assistant", "content": "Understood. 我已理解之前的对话上下文，继续执行。"},
            ]

            logger.info(f"Auto-compact 完成，压缩后 {self.state.estimate_tokens()} tokens")

        except Exception as e:
            logger.error(f"Auto-compact 失败: {e}")
            # 失败时不中断循环，只是不压缩
