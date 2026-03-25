"""
Orchestrator - 主Agent，负责理解需求、生成计划、调度执行、评估结果、汇总交付
"""
import json
import time
import uuid
import os
import asyncio
from core.config import Config
from core.llm_client import LLMClient, LLMCancelledError
from core.agent_registry import AgentRegistry
from core.internal_tools import InternalTools
from core.prompt_builder import build_orchestrator_prompt
from core.logger import logger


class Orchestrator:
    """主Agent - 全局指挥官"""

    # 状态
    STATE_IDLE = "idle"
    STATE_EXECUTING = "executing"
    STATE_PAUSED = "paused"

    def __init__(self, config: Config, llm_client: LLMClient,
                 agent_registry: AgentRegistry, internal_tools: InternalTools = None):
        self.config = config
        self.llm_client = llm_client
        self.agent_registry = agent_registry
        self.internal_tools = internal_tools
        self.system_prompt = ""
        self.state = self.STATE_IDLE
        self._paused = False

        # 任务上下文
        self.task_id = ""
        self.user_request = ""
        self.plan = {}
        self.step_results = {}
        self.conversation_history = []
        self.context_rounds = 20  # 上下文轮次（可配置）

        # 工作流暂停-恢复（方案B：return + resume）
        self._paused_step_info = None

    def initialize(self):
        """初始化 Orchestrator，生成动态 System Prompt"""
        manifests = self.agent_registry.get_all_manifests()
        tool_defs = self.internal_tools.get_tool_definitions()
        self.system_prompt = build_orchestrator_prompt(manifests, tool_defs)
        logger.info("Orchestrator 初始化完成")

    # ════════════════════════════════════════
    # 暂停 / 恢复
    # ════════════════════════════════════════

    @staticmethod
    def _try_parse_need_input(result: str) -> dict | None:
        """检测 Agent 返回是否为 need_input 请求"""
        if not result or not result.strip().startswith('{'):
            return None
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict) and parsed.get("type") == "need_input":
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    def is_paused(self) -> bool:
        return self._paused_step_info is not None

    def pause(self):
        """暂停当前执行并取消正在进行的 LLM 调用"""
        self._paused = True
        self.llm_client.cancel()
        logger.info("执行已暂停（含 LLM 中断）")

    def resume(self):
        """恢复执行"""
        self._paused = False
        self.llm_client.reset_cancel()
        logger.info("执行已恢复")

    # ════════════════════════════════════════
    # LLM 日志
    # ════════════════════════════════════════

    def _flush_llm_log(self, phase: str):
        """刷出累积的 LLM 调用日志，yield llm_log 事件"""
        if not hasattr(self, '_llm_call_log'):
            return
        while self._llm_call_log:
            call_info = self._llm_call_log.pop(0)
            yield {"type": "llm_log", "data": {
                "phase": phase,
                "model": call_info.get("model", ""),
                "messages": call_info.get("messages", []),
                "response": call_info.get("response", ""),
                "prompt_tokens": call_info.get("prompt_tokens", 0),
                "completion_tokens": call_info.get("completion_tokens", 0),
                "elapsed": call_info.get("elapsed", 0),
            }}

    def _init_llm_log(self):
        """注册 LLM 调用日志回调"""
        self._llm_call_log = []
        self.llm_client.on_call = lambda info: self._llm_call_log.append(info)

    # ════════════════════════════════════════
    # Web API 入口
    # ════════════════════════════════════════

    async def run_stream(self, user_input: str):
        """
        主入口：意图理解 → (chat回复 | clarify追问 | 生成计划等确认)
        """
        self.task_id = f"task_{uuid.uuid4().hex[:8]}"
        self.user_request = user_input
        self.step_results = {}
        self.llm_client.reset_task_stats()
        start_time = time.time()
        self._init_llm_log()

        # ── 意图理解 ──
        yield {"type": "thinking", "data": {"message": "正在理解你的需求..."}}
        intent_result = self._understand_intent(user_input)
        intent_type = intent_result.get("intent_type", "execute")
        yield {"type": "intent", "data": {"intent_type": intent_type, "understanding": intent_result.get("understanding", "")}}

        for evt in self._flush_llm_log("intent"):
            yield evt

        # ── 内部工具 ──
        tools_needed = intent_result.get("tools_needed", [])
        tool_context = ""
        if tools_needed:
            yield {"type": "thinking", "data": {"message": "正在执行内部工具..."}}
            tool_results = self._execute_internal_tools(tools_needed)
            tool_context = "\n\n---\n\n".join(tool_results)

        # ── clarify ──
        if intent_type == "clarify":
            questions = intent_result.get("clarification_questions", [])
            if not questions:
                questions = ["请提供更多细节，以便我更好地帮你完成任务。"]
            yield {"type": "clarify", "data": {"questions": questions, "task_id": self.task_id}}
            return

        # ── chat ──
        if intent_type == "chat":
            if tool_context:
                try:
                    reply = self._chat_with_tools_loop(user_input, tool_context)
                except Exception:
                    reply = tool_context
            else:
                reply = intent_result.get("reply") or "你好！我是多 Agent 工作台助手。请告诉我你需要做什么？"

            self.conversation_history.append({"role": "user", "content": user_input})
            self.conversation_history.append({"role": "assistant", "content": reply})
            stats = self.llm_client.get_task_stats()
            yield {"type": "reply", "data": {"content": reply}}
            yield {"type": "done", "data": {"stats": stats, "elapsed": time.time() - start_time}}
            return

        # ── execute: 生成计划 ──
        logger.info(f"创建任务: {self.task_id}")
        yield {"type": "thinking", "data": {"message": "正在生成执行计划..."}}
        plan = self._generate_plan(user_input)

        for evt in self._flush_llm_log("plan"):
            yield evt

        if not plan:
            reply = (getattr(self, '_plan_fallback_reply', '') or
                     intent_result.get("reply") or
                     "抱歉，我暂时无法为这个请求生成执行计划。请换个说法再试。")
            self.conversation_history.append({"role": "user", "content": user_input})
            self.conversation_history.append({"role": "assistant", "content": reply})
            stats = self.llm_client.get_task_stats()
            yield {"type": "reply", "data": {"content": reply}}
            yield {"type": "done", "data": {"stats": stats, "elapsed": time.time() - start_time}}
            return

        self.plan = plan
        yield {"type": "plan", "data": plan}
        yield {"type": "wait_confirm", "data": {"task_id": self.task_id}}

    # ════════════════════════════════════════
    # 计划执行（拆分为子函数）
    # ════════════════════════════════════════

    async def run_plan_stream(self, step_models: dict = None, resume_answer: str = None):
        """
        执行已确认的计划，yield 每步事件。
        resume_answer: 恢复暂停步骤时传入的用户回答
        """
        plan = self.plan
        steps = plan.get("steps", [])
        total = len(steps)
        step_models = step_models or {}

        # 恢复模式 vs 全新执行
        if resume_answer and self._paused_step_info:
            completed = set(self.step_results.keys())
            paused_step_id = self._paused_step_info["step"]["step_id"]
            pause_type = self._paused_step_info.get("pause_type", "")
            logger.info(f"恢复工作流: {len(completed)}/{total} 步已完成, "
                        f"暂停步骤={paused_step_id}, 类型={pause_type}")

            # 处理逐步审查的用户操作
            if pause_type == "step_review":
                action = resume_answer.strip().lower()
                reviewed_step_id = self._paused_step_info.get("completed_step_id", paused_step_id)

                if action == "retry":
                    # 重试：从已完成中移除，下一轮循环会重新执行
                    completed.discard(reviewed_step_id)
                    self.step_results.pop(reviewed_step_id, None)
                    logger.info(f"用户选择重试 Step {reviewed_step_id}")
                elif action.startswith("edit:"):
                    # 修改输出：用用户内容替换
                    new_content = resume_answer[5:].strip()
                    if reviewed_step_id in self.step_results:
                        self.step_results[reviewed_step_id]["data"] = new_content
                    logger.info(f"用户修改了 Step {reviewed_step_id} 的输出")
                else:
                    # continue 或其他 → 直接继续
                    logger.info(f"用户确认继续，Step {reviewed_step_id} 结果保留")

                self._paused_step_info = None
                resume_answer = None
        else:
            completed = set()

        self._init_llm_log()
        self.state = self.STATE_EXECUTING
        start_time = time.time()

        while len(completed) < total:
            ready_steps = [
                s for s in steps
                if s["step_id"] not in completed
                and all(dep in completed for dep in s.get("depends_on", []))
            ]
            if not ready_steps:
                yield {"type": "error", "data": {"message": "死锁：没有可执行的步骤"}}
                break

            for step in ready_steps:
                step_id = step["step_id"]

                # 发送 step_start
                yield {"type": "step_start", "data": {
                    "step_id": step_id,
                    "total": total,
                    "agent": step.get("agent", ""),
                    "description": step.get("description", ""),
                    "input": step.get("input", {}),
                }}

                # 暂停检查（用户手动暂停按钮）
                async for evt in self._check_paused(step_id):
                    yield evt

                # 执行单步
                result = None
                async for evt in self._execute_single_step(step, step_models, resume_answer):
                    if evt["type"] == "__result__":
                        result = evt["data"]
                    elif evt["type"] in ("step_pause", "paused"):
                        yield evt
                        if evt["type"] == "step_pause":
                            for log_evt in self._flush_llm_log(f"step_{step_id}_pause"):
                                yield log_evt
                            return
                    else:
                        yield evt

                # 如果 resume_answer 已被使用，清空
                if resume_answer and not self._paused_step_info:
                    resume_answer = None

                # result 为 None 表示被取消并等待恢复，continue 重试
                if result is None:
                    continue

                step_elapsed = result["elapsed"]
                step_tokens = result["tokens"]
                raw_result = result["output"]
                quality = result.get("quality", "good")

                # 保存结果
                envelope = {
                    "status": "ok" if quality != "none" else "no_data",
                    "data": raw_result,
                    "metadata": {
                        "agent": step.get("agent", ""),
                        "step_id": step_id,
                        "elapsed": round(step_elapsed, 1),
                        "tokens": step_tokens,
                        "reflect_quality": quality,
                    }
                }
                self.step_results[step_id] = envelope
                completed.add(step_id)

                yield {"type": "step_result", "data": {
                    "step_id": step_id,
                    "output": raw_result,
                    "elapsed": round(step_elapsed, 1),
                    "tokens": step_tokens,
                    "status": "completed" if quality != "none" else "warning",
                }}

                for log_evt in self._flush_llm_log(f"step_{step_id}"):
                    yield log_evt

                # ── 逐步审查：每步完成后自动暂停 ──
                if len(completed) < total:
                    self._paused_step_info = {
                        "step": step,
                        "agent_state": {},
                        "step_input": step.get("input", {}),
                        "pause_type": "step_review",
                        "completed_step_id": step_id,
                    }
                    self.state = self.STATE_PAUSED

                    yield {"type": "step_review", "data": {
                        "step_id": step_id,
                        "output": raw_result[:2000],
                        "next_step": self._get_next_step_preview(steps, completed),
                    }}
                    return  # SSE 流结束，等用户操作

        # ── 汇总 ──
        yield {"type": "thinking", "data": {"message": "正在汇总结果..."}}
        final_result = self._summarize_results(plan)

        for evt in self._flush_llm_log("summarize"):
            yield evt

        # 保存
        self.state = self.STATE_IDLE
        output_dir = self.config.output_dir
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"{self.task_id}.md")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"# {plan.get('goal', '任务结果')}\n\n")
            f.write(final_result)

        self.conversation_history.append({"role": "user", "content": self.user_request})
        self.conversation_history.append({"role": "assistant", "content": final_result[:500]})

        elapsed = time.time() - start_time
        stats = self.llm_client.get_task_stats()
        yield {"type": "summary", "data": {"content": final_result, "output_file": output_file}}
        yield {"type": "done", "data": {"stats": stats, "elapsed": round(elapsed, 1)}}

    async def _check_paused(self, step_id):
        """检查前端暂停按钮，阻塞直到恢复"""
        while self._paused:
            self.state = self.STATE_PAUSED
            yield {"type": "paused", "data": {"step_id": step_id}}
            await asyncio.sleep(1)
        if self.state == self.STATE_PAUSED:
            self.state = self.STATE_EXECUTING

    @staticmethod
    def _get_next_step_preview(steps, completed):
        """获取下一步预览信息"""
        for s in steps:
            if s["step_id"] not in completed and all(
                dep in completed for dep in s.get("depends_on", [])
            ):
                return {"step_id": s["step_id"], "description": s.get("description", ""), "agent": s.get("agent", "")}
        return None

    async def _execute_single_step(self, step, step_models, resume_answer=None):
        """
        执行单个步骤。yield 事件：
        - __result__: 执行结果（内部消费，不发给前端）
        - step_pause: 需要用户输入
        - step_reflect: 反思评估
        - step_start: 重试时的新开始
        - paused: 取消后暂停等待
        """
        step_id = step["step_id"]
        agent_name = step.get("agent", "")
        step_input = step.get("input", {})

        try:
            # 临时切换模型
            original_model = None
            if step_id in step_models and step_models[step_id]:
                original_model = self.config.role_models.get(agent_name)
                self.config.role_models[agent_name] = step_models[step_id]
                logger.info(f"Step {step_id}: 临时切换模型 → {step_models[step_id]}")

            context = self._assemble_context(step)
            agent = self.agent_registry.get_agent(agent_name)
            step_start = time.time()

            # 恢复模式：注入用户回答
            if resume_answer and self._paused_step_info and self._paused_step_info["step"]["step_id"] == step_id:
                step_input["user_answer"] = resume_answer
                step_input["_agent_state"] = self._paused_step_info.get("agent_state", {})
                if self._paused_step_info.get("pause_type") == "pause_after":
                    step_input["user_feedback"] = resume_answer
                self._paused_step_info = None

            result = await asyncio.to_thread(agent.execute, step_input, context)

            # ── need_input → 保存状态并暂停 ──
            need_input = self._try_parse_need_input(result)
            if need_input:
                questions = need_input.get("questions", ["请提供更多信息"])
                self._paused_step_info = {
                    "step": step, "agent_state": need_input.get("state", {}),
                    "step_input": step_input, "pause_type": "need_input",
                }
                self.state = self.STATE_PAUSED
                logger.info(f"Step {step_id}: Agent 请求用户输入 → 暂停")
                yield {"type": "step_pause", "data": {
                    "step_id": step_id, "agent": agent_name,
                    "questions": questions, "message": need_input.get("message", ""),
                }}
                return

            step_elapsed = time.time() - step_start
            step_tokens = self.llm_client.get_task_stats().get("task_tokens", 0)

            # ── pause_after ──
            if step.get("pause_after"):
                self._paused_step_info = {
                    "step": step, "agent_state": {},
                    "step_input": step_input, "pause_type": "pause_after",
                    "result_preview": result[:500],
                }
                self.state = self.STATE_PAUSED
                yield {"type": "step_pause", "data": {
                    "step_id": step_id, "agent": agent_name,
                    "questions": ["请查看以上步骤结果，是否需要调整？"],
                    "message": result[:500],
                }}
                return

            # ── 反思评估 ──
            reflection = self._reflect_on_step(step, result)
            quality = reflection.get("quality", "good")

            yield {"type": "step_reflect", "data": {
                "step_id": step_id,
                "quality": quality,
                "reason": reflection.get("reason", ""),
            }}

            # 质量差 → 重试一次
            if quality == "poor":
                result, step_elapsed, quality = await self._retry_poor_quality(
                    step, step_input, context, agent, agent_name,
                    result, step_elapsed, reflection
                )

            if quality == "none":
                result = f"[未找到相关数据] {reflection.get('reason', '')}\n\n原始返回：\n{result[:500]}"

            yield {"type": "__result__", "data": {
                "output": result,
                "elapsed": step_elapsed,
                "tokens": step_tokens,
                "quality": quality,
            }}

        except LLMCancelledError:
            logger.info(f"Step {step_id} 被用户取消")
            yield {"type": "step_result", "data": {
                "step_id": step_id, "output": "✉️ 步骤已被用户中断",
                "elapsed": 0, "tokens": 0, "status": "cancelled",
            }}
            # 等待恢复
            while self._paused:
                self.state = self.STATE_PAUSED
                yield {"type": "paused", "data": {"step_id": step_id}}
                await asyncio.sleep(1)
            self.state = self.STATE_EXECUTING
            # result=None → 外层 continue 重试
            yield {"type": "__result__", "data": None}

        except Exception as e:
            logger.error(f"Step {step_id} 执行失败: {e}")
            self.step_results[step_id] = {
                "status": "error", "data": f"[失败] {e}",
                "metadata": {"agent": agent_name, "step_id": step_id},
            }
            yield {"type": "__result__", "data": {
                "output": str(e), "elapsed": 0, "tokens": 0, "quality": "error",
            }}

        finally:
            if original_model is not None:
                self.config.role_models[agent_name] = original_model

    async def _retry_poor_quality(self, step, step_input, context, agent, agent_name,
                                   original_result, original_elapsed, reflection):
        """质量差时用改进参数重试一次，返回 (result, elapsed, quality)"""
        step_id = step["step_id"]
        retry_suggestion = reflection.get("retry_suggestion", {})
        new_queries = retry_suggestion.get("queries", [])

        if not new_queries or agent_name != "web_search":
            return original_result, original_elapsed, "poor"

        logger.info(f"Step {step_id}: 质量不佳，重试搜索: {new_queries}")
        retry_input = {**step_input, "queries": new_queries}

        retry_start = time.time()
        retry_result = await asyncio.to_thread(agent.execute, retry_input, context)
        retry_elapsed = time.time() - retry_start

        retry_ref = self._reflect_on_step(step, retry_result)
        retry_quality = retry_ref.get("quality", "good")

        if retry_quality != "none":
            logger.info(f"Step {step_id}: 重试成功，quality={retry_quality}")
            return retry_result, original_elapsed + retry_elapsed, retry_quality
        else:
            result = (f"[未找到相关数据] 两次搜索均未找到相关数据。\n\n"
                      f"原始结果：\n{original_result[:500]}\n\n重试结果：\n{retry_result[:500]}")
            return result, original_elapsed + retry_elapsed, "none"

    async def retry_step(self, step_id: str, step_models: dict = None):
        """重试指定的失败步骤"""
        if not self.plan:
            yield {"type": "error", "data": {"message": "没有活跃的计划"}}
            return

        steps = self.plan.get("steps", [])
        target_step = next((s for s in steps if s["step_id"] == step_id), None)
        if not target_step:
            yield {"type": "error", "data": {"message": f"步骤 {step_id} 不存在"}}
            return

        agent_name = target_step.get("agent", "")
        step_input = target_step.get("input", {})
        step_models = step_models or {}

        yield {"type": "step_start", "data": {
            "step_id": step_id, "total": len(steps),
            "agent": agent_name, "description": target_step.get("description", ""),
            "input": step_input,
        }}

        try:
            original_model = None
            if step_id in step_models and step_models[step_id]:
                original_model = self.config.role_models.get(agent_name)
                self.config.role_models[agent_name] = step_models[step_id]

            context = self._assemble_context(target_step)
            agent = self.agent_registry.get_agent(agent_name)
            step_start_t = time.time()
            result = await asyncio.to_thread(agent.execute, step_input, context)
            step_elapsed = time.time() - step_start_t

            step_tokens = self.llm_client.get_task_stats()
            self.step_results[step_id] = result

            yield {"type": "step_result", "data": {
                "step_id": step_id, "output": result[:3000],
                "elapsed": round(step_elapsed, 1),
                "tokens": step_tokens.get("task_tokens", 0),
                "status": "completed",
            }}
        except Exception as e:
            logger.error(f"Step {step_id} 重试失败: {e}")
            self.step_results[step_id] = f"[失败] {e}"
            yield {"type": "step_result", "data": {
                "step_id": step_id, "output": str(e),
                "elapsed": 0, "tokens": 0, "status": "failed",
            }}
        finally:
            if original_model is not None:
                self.config.role_models[agent_name] = original_model

        yield {"type": "stream_end", "data": {}}

    # ════════════════════════════════════════
    # LLM 决策
    # ════════════════════════════════════════

    def _understand_intent(self, user_input: str) -> dict:
        """意图理解：execute / clarify / chat"""
        logger.debug("Orchestrator 开始理解意图")

        intent_system = f"""你是多 Agent 工作台的意图理解模块。当前时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}

你的职责：理解用户想做什么，并判断信息是否完整。

## 可用能力
{chr(10).join(f"- {name}: {m.get('description','')}" for name, m in self.agent_registry.get_all_manifests().items())}

## 判断规则
1. 如果用户的请求可以通过 Agent 完成，检查信息是否完整：
   - 缺少关键信息 → intent_type = "clarify"
   - 信息足够 → intent_type = "execute"
2. 纯闲聊/感谢 → intent_type = "chat"
3. 查系统信息 → intent_type = "chat"，在 tools_needed 中列出工具"""

        messages = [{"role": "system", "content": intent_system}]
        messages.extend(self.conversation_history[-self.context_rounds:])
        messages.append(
            {"role": "user", "content": f"""用户输入: "{user_input}"

以 JSON 格式回答：
{{
  "intent_type": "execute | clarify | chat",
  "understanding": "你对用户需求的理解（一句话）",
  "clarification_questions": ["仅当 clarify 时列出问题"],
  "reply": "仅当 chat 时给出回复",
  "tools_needed": []
}}

关键原则：
- 缺少关键信息就必须追问（clarify），不要猜测
- 例如"查天气"但没说城市 → clarify
- 信息完整时 intent_type = "execute"
- 纯闲聊 → chat"""}
        )

        try:
            result = self.llm_client.call_json(messages, role="orchestrator", temperature=0.3)
        except Exception as e:
            logger.warning(f"意图理解失败: {e}")
            result = {"intent_type": "chat", "reply": "抱歉，理解输入时遇到问题，请重试。", "tools_needed": []}

        logger.debug(f"意图: {result.get('intent_type', 'execute')}", indent=1)
        return result

    def _generate_plan(self, user_input: str) -> dict:
        """生成结构化执行计划"""
        logger.info("Orchestrator 生成执行计划")
        agent_schema = self._build_agent_schema_prompt()

        plan_system = """你是一个任务规划专家。你的唯一职责是为用户的需求生成结构化执行计划。
规则：
1. 必须输出合法 JSON，包含 goal 和 steps
2. 每个步骤的 input 字段必须严格匹配下方给出的 Agent 参数 Schema
3. 不要发明新的字段名，只用 Schema 中定义的字段
4. 不要评估需求是否合适，不要拒绝请求"""

        messages = [{"role": "system", "content": plan_system}]
        messages.extend(self.conversation_history[-self.context_rounds:])
        messages.append(
            {"role": "user", "content": f"""用户需求: "{user_input}"

## 可用 Agent 及其参数 Schema

{agent_schema}

## 输出格式

严格按以下 JSON 格式输出，input 字段必须匹配上方 Schema：
{{
  "goal": "任务目标描述",
  "steps": [
    {{
      "step_id": 1,
      "description": "步骤描述",
      "agent": "agent名称",
      "input": {{ /* 严格按该 Agent 的 Schema 填写 */ }},
      "depends_on": [],
      "pause_after": false
    }}
  ]
}}"""}
        )

        plan = self.llm_client.call_json(messages, role="orchestrator", temperature=0.3)

        steps = plan.get("steps", [])
        if not isinstance(steps, list) or len(steps) == 0 or "goal" not in plan:
            logger.warning(f"计划结构无效: {list(plan.keys())}")
            self._plan_fallback_reply = plan.get("response") or plan.get("reply") or ""
            return None

        plan = self._validate_plan_schema(plan)
        self._plan_fallback_reply = ""
        logger.debug(f"计划包含 {len(steps)} 个步骤", indent=1)
        return plan

    # ════════════════════════════════════════
    # 辅助函数
    # ════════════════════════════════════════

    def _execute_internal_tools(self, tools_needed: list) -> list[str]:
        """执行内部工具调用"""
        results = []
        for tool_call in tools_needed:
            if isinstance(tool_call, str):
                tool_name, tool_params = tool_call, {}
            elif isinstance(tool_call, dict):
                tool_name = tool_call.get("name", "")
                tool_params = tool_call.get("params", {})
            else:
                continue
            result = self.internal_tools.call(tool_name, tool_params)
            results.append(f"### {tool_name} 执行结果\n\n{result}")
        return results

    def _chat_with_tools_loop(self, user_input: str, initial_context: str, max_rounds: int = 5) -> str:
        """多轮工具调用循环，直到 LLM 给出最终回复"""
        context = initial_context

        for round_num in range(max_rounds):
            logger.debug(f"工具循环 第{round_num + 1}轮", indent=1)
            messages = [
                {"role": "system", "content": """你是多Agent工作台的智能助手。根据工具执行结果回复用户。

如果还需要执行更多操作，返回 JSON：
{"reply": "简短说明", "tools_needed": [{"name": "工具名", "params": {...}}]}

如果已完成，返回 JSON：
{"reply": "最终回复", "tools_needed": []}"""},
                {"role": "user", "content": f"""用户请求: "{user_input}"

工具执行结果:

{context}

请决定：继续调用工具？还是直接回复？"""},
            ]

            try:
                result = self.llm_client.call_json(messages, role="orchestrator", temperature=0.3)
            except Exception:
                return self.llm_client.call(messages, role="orchestrator", temperature=0.5)

            next_tools = result.get("tools_needed", [])
            reply = result.get("reply", "")

            if not next_tools:
                return reply

            new_results = self._execute_internal_tools(next_tools)
            context += "\n\n---\n\n" + "\n\n---\n\n".join(new_results)

        return reply or context

    def _build_agent_schema_prompt(self) -> str:
        """从 agent manifests 构建 Schema 描述"""
        lines = []
        for name, manifest in self.agent_registry.get_all_manifests().items():
            lines.append(f"### Agent: `{name}`")
            lines.append(f"描述: {manifest.get('description', '')}")
            schema = manifest.get("input_schema", {})
            if schema:
                lines.append("input 参数（必须严格使用以下字段名）:")
                for field_name, field_info in schema.items():
                    ftype = field_info.get("type", "string")
                    required = "必填" if field_info.get("required") else f"可选, 默认={field_info.get('default', 'null')}"
                    desc = field_info.get("description", "")
                    enum_vals = field_info.get("enum")
                    enum_str = f", 可选值: {enum_vals}" if enum_vals else ""
                    lines.append(f"  - `{field_name}` ({ftype}, {required}): {desc}{enum_str}")
            lines.append("")
        return "\n".join(lines)

    def _validate_plan_schema(self, plan: dict) -> dict:
        """校验计划中每步 input 是否匹配 Agent schema，自动修正常见错误"""
        steps = plan.get("steps", [])
        all_manifests = self.agent_registry.get_all_manifests()

        for step in steps:
            step_id = step.get("step_id", "?")
            agent_name = step.get("agent", "")
            step_input = step.get("input", {})

            if agent_name not in all_manifests:
                continue

            schema = all_manifests[agent_name].get("input_schema", {})
            if not schema:
                continue

            for field_name, field_info in schema.items():
                if field_name in step_input or not field_info.get("required"):
                    continue

                # 必填字段缺失 → 尝试别名修正
                aliases = self._get_field_aliases(field_name)
                for alias in aliases:
                    if alias in step_input:
                        val = step_input.pop(alias)
                        if "list" in field_info.get("type", "") and isinstance(val, str):
                            val = [val]
                        step_input[field_name] = val
                        logger.warning(f"Step {step_id}: Schema 修正 '{alias}' → '{field_name}'")
                        break
                else:
                    logger.error(f"Step {step_id}: 必填字段 '{field_name}' 缺失 (Agent: {agent_name})")

            step["input"] = step_input

        plan["steps"] = steps
        return plan

    @staticmethod
    def _get_field_aliases(field_name: str) -> list[str]:
        """常见的 LLM 字段名混淆映射"""
        alias_map = {
            "queries": ["query", "keywords", "search_queries", "search_query"],
            "requirement": ["requirements", "analysis_requirement", "task"],
            "doc_requirement": ["requirement", "requirements", "document_requirement"],
            "topics": ["topic", "interview_topics", "questions"],
            "content": ["text", "input_text", "data"],
        }
        return alias_map.get(field_name, [])

    def _assemble_context(self, step: dict) -> str:
        """组装上下文：将 depends_on 步骤的输出拼入"""
        depends_on = step.get("depends_on", [])
        source_steps = step.get("input", {}).get("source_steps", [])
        all_deps = sorted(set(depends_on + source_steps))
        if not all_deps:
            return ""

        parts = []
        for dep_id in all_deps:
            if dep_id in self.step_results:
                result = self.step_results[dep_id]
                result_text = result["data"] if isinstance(result, dict) and "data" in result else str(result)
                parts.append(f"## Step {dep_id} 的输出\n\n{result_text}")
        return "\n\n---\n\n".join(parts)

    def _reflect_on_step(self, step: dict, result: str) -> dict:
        """反思评估步骤结果质量"""
        result_preview = result[:2000] if result else "[空结果]"

        messages = [
            {"role": "system", "content": """你是一个质量评估专家。严格按JSON格式输出。

评估标准：
- "good": 结果包含用户需要的具体数据点
- "poor": 有内容但缺少关键数据，换搜索词可能更好
- "none": 空结果、报错、或完全不相关"""},
            {"role": "user", "content": f"""任务: {self.plan.get('goal', '')}
步骤: {step.get('description', '')} (Agent: {step.get('agent', '')})
输入: {json.dumps(step.get('input', {}), ensure_ascii=False)}

执行结果（前2000字符）:
{result_preview}

输出JSON:
{{
  "quality": "good|poor|none",
  "reason": "一句话评估原因",
  "retry_suggestion": {{
    "queries": ["仅当 poor 时给出改进搜索词"]
  }}
}}"""},
        ]

        try:
            reflection = self.llm_client.call_json(messages, role="orchestrator", temperature=0.2)
            quality = reflection.get("quality", "good")
            logger.info(f"Step {step['step_id']} 反思: quality={quality}")
            return reflection
        except Exception as e:
            logger.warning(f"反思评估失败: {e}")
            return {"quality": "good", "reason": "评估失败，默认通过"}

    def _summarize_results(self, plan: dict) -> str:
        """汇总所有步骤结果"""
        parts = []
        for sid, envelope in sorted(self.step_results.items()):
            if isinstance(envelope, dict) and "status" in envelope:
                status = envelope["status"]
                data = envelope.get("data", "")
                label = {"ok": "✅ 数据正常", "no_data": "⚠️ 未找到数据", "error": "❌ 执行失败"}.get(status, status)
                parts.append(f"## Step {sid} [{label}]\n\n{data}")
            else:
                parts.append(f"## Step {sid}\n\n{envelope}")

        all_outputs = "\n\n---\n\n".join(parts)

        messages = [
            {"role": "system", "content": """你是报告整合专家。将多步结果整合为用户友好的交付物。
原则：只基于实际数据，绝不编造，如实告知缺失部分。"""},
            {"role": "user", "content": f"""任务目标: {plan.get('goal', '')}

各步骤结果：

{all_outputs}

请生成最终交付物。标记为未找到数据/执行失败的部分如实告知用户。"""},
        ]

        return self.llm_client.call(messages, role="orchestrator")
