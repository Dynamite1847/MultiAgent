"""
Orchestrator - 主Agent，负责理解需求、生成计划、调度执行、评估结果、汇总交付
"""
import json
import time
import uuid
import os
from core.config import Config
from core.llm_client import LLMClient
from core.agent_registry import AgentRegistry
from core.internal_tools import InternalTools
from core.prompt_builder import build_orchestrator_prompt
from core.logger import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm

console = Console()


class Orchestrator:
    """主Agent - 全局指挥官"""

    # 状态定义
    STATE_IDLE = "idle"
    STATE_UNDERSTANDING = "understanding"
    STATE_CLARIFYING = "clarifying"
    STATE_PLANNING = "planning"
    STATE_CONFIRMING_PLAN = "confirming_plan"
    STATE_EXECUTING = "executing"
    STATE_PAUSED = "paused"
    STATE_SUMMARIZING = "summarizing"
    STATE_DONE = "done"

    def __init__(self, config: Config, llm_client: LLMClient,
                 agent_registry: AgentRegistry, internal_tools: InternalTools = None):
        self.config = config
        self.llm_client = llm_client
        self.agent_registry = agent_registry
        self.internal_tools = internal_tools
        self.system_prompt = ""
        self.state = self.STATE_IDLE

        # 当前任务上下文
        self.task_id = ""
        self.user_request = ""
        self.plan = {}
        self.step_results = {}  # step_id -> result string
        self.conversation_history = []  # 跨轮次对话历史（持久）

    def initialize(self):
        """初始化 Orchestrator，生成动态 System Prompt"""
        manifests = self.agent_registry.get_all_manifests()
        tool_defs = self.internal_tools.get_tool_definitions()
        self.system_prompt = build_orchestrator_prompt(manifests, tool_defs)
        logger.info("Orchestrator 初始化完成")

    def run(self, user_input: str):
        """
        主流程入口：接收用户输入，执行完整流程
        """
        self.task_id = f"task_{uuid.uuid4().hex[:8]}"
        self.user_request = user_input
        self.step_results = {}
        # 注意：conversation_history 不在这里重置，保持跨轮次记忆

        logger.info(f"收到用户输入: \"{user_input}\"")
        self.llm_client.reset_task_stats()

        start_time = time.time()

        # ── Step 1: 意图理解 ──
        self.state = self.STATE_UNDERSTANDING
        intent_result = self._understand_intent(user_input)
        intent_type = intent_result.get("intent_type", "task")

        # ── Step 1b: 统一执行内部工具（无论什么 intent 都由编排器处理）──
        tools_needed = intent_result.get("tools_needed", [])
        tool_context = ""
        if tools_needed:
            tool_results = self._execute_internal_tools(tools_needed)
            tool_context = "\n\n---\n\n".join(tool_results)

        # ── Step 2: 按意图类型分流 ──
        if intent_type in ("chat", "system_command", "unclear"):
            # 非任务意图：多轮工具调用 + 回复
            if tool_context:
                try:
                    reply = self._chat_with_tools_loop(user_input, tool_context)
                except Exception as e:
                    logger.warning(f"LLM 回复生成失败，直接展示工具结果: {e}")
                    reply = tool_context
            else:
                reply = intent_result.get("reply", "你好！有什么可以帮你的？")

            # 记录对话历史
            self.conversation_history.append({"role": "user", "content": user_input})
            self.conversation_history.append({"role": "assistant", "content": reply})

            # 显示
            color = "yellow" if intent_type == "unclear" else "cyan"
            console.print(f"\n[{color}]{reply}[/{color}]")
            task_stats = self.llm_client.get_task_stats()
            console.print(f"[dim](本次交互: {task_stats['task_calls']}次调用, {task_stats['task_tokens']} tokens)[/dim]\n")

            # system_command 特殊处理：退出
            if intent_type == "system_command":
                command = intent_result.get("command", "").lower().strip()
                if command in ("quit", "exit", "退出", "关闭", "结束"):
                    raise SystemExit(0)
            return

        # ── 以下是 intent_type == "task" 的正式流程 ──
        logger.info(f"创建任务: {self.task_id}")

        # ── Step 2: 需求澄清（如果需要）──
        if intent_result.get("needs_clarification"):
            self.state = self.STATE_CLARIFYING
            user_input = self._clarify(intent_result)

        # ── Step 3: 生成执行计划 ──
        self.state = self.STATE_PLANNING
        plan = self._generate_plan(user_input)
        self.plan = plan

        # ── Step 4: 展示计划，等待用户确认 ──
        self.state = self.STATE_CONFIRMING_PLAN
        confirmed = self._confirm_plan(plan)
        if not confirmed:
            logger.info("用户取消任务")
            console.print("\n[yellow]任务已取消[/yellow]")
            return

        # ── Step 5: 逐步执行 ──
        self.state = self.STATE_EXECUTING
        logger.info("用户确认执行")
        self._execute_plan(plan)

        # ── Step 6: 汇总结果 ──
        self.state = self.STATE_SUMMARIZING
        final_result = self._summarize_results(plan)

        # ── Step 7: 展示 & 保存 ──
        self.state = self.STATE_DONE
        self._deliver_result(final_result)

        elapsed = time.time() - start_time
        task_stats = self.llm_client.get_task_stats()
        global_stats = self.llm_client.get_stats()
        logger.info(f"任务完成")
        logger.info(
            f"本次任务: {task_stats['task_calls']}次LLM调用, "
            f"{task_stats['task_tokens']} tokens, 耗时{elapsed:.0f}秒"
        )
        logger.info(
            f"累计: {global_stats['total_calls']}次调用, "
            f"{global_stats['total_tokens']} tokens"
        )

    # ────────────────────────────────────────────
    # 各阶段实现
    # ────────────────────────────────────────────

    def _understand_intent(self, user_input: str) -> dict:
        """
        意图理解：先判断 intent_type，再决定后续流程
        包含对话历史以保持上下文
        """
        logger.debug("Orchestrator 开始理解意图")

        messages = [
            {"role": "system", "content": self.system_prompt},
        ]

        # 添加对话历史（限制最近 10 轮避免 token 爆炸）
        history_window = self.conversation_history[-20:]  # 最近 10 轮（20条消息）
        if history_window:
            logger.debug(f"携带 {len(history_window)//2} 轮对话历史", indent=1)
        messages.extend(history_window)

        messages.append(
            {"role": "user", "content": f"""用户输入: "{user_input}"

请先判断用户输入的意图类型，然后给出相应的回应。

以JSON格式回答：
{{
  "intent_type": "task / chat / system_command / unclear",
  "understanding": "你对用户输入的理解",
  "needs_clarification": false,
  "clarification_questions": [],
  "reply": "对于 chat/system_command/unclear 类型的直接回复",
  "command": "对于 system_command 类型，识别的指令名（如 quit/exit/help）",
  "tools_needed": []
}}

关键规则：
- 只有真正的工作任务（调研、写文档、分析等）才是 "task"
- 打招呼、闲聊、问功能、感谢、告别等都是 "chat"
- "退出"、"关闭"、"结束" 等都是 "system_command"
- reply 字段：对于 chat 类型要友好自然地回复；对于 system_command 解释将执行什么操作
- 对于 task 类型，reply 字段可以为空
- tools_needed：如果需要查询信息或执行操作，列出需要调用的内部工具（read_file / write_file / list_directory）
  - 例如用户问"用的什么模型" → tools_needed: [{{"name": "read_file", "params": {{"path": "config.yaml"}}}}]
  - 例如用户问"有哪些Agent" → tools_needed: [{{"name": "list_directory", "params": {{"path": "agents"}}}}]
  - 用户要求修改配置 → 先 read_file 读取当前内容，再 write_file 写入修改后的内容
  - 如果不需要调用工具，tools_needed 为空数组
  - 当 tools_needed 非空时，reply 字段可以写一个简短的过渡语"""}
        )

        try:
            result = self.llm_client.call_json(messages, role="orchestrator", temperature=0.3)
        except (ValueError, Exception) as e:
            # JSON 解析失败或 LLM 调用失败 → 降级为 chat 回复
            logger.warning(f"意图理解失败，降级为 chat: {e}")
            # 尝试获取原始响应作为回复
            result = {
                "intent_type": "chat",
                "reply": f"抱歉，我在理解你的输入时遇到了问题。请重试或换个说法。(错误: {type(e).__name__})",
                "tools_needed": [],
            }

        intent_type = result.get("intent_type", "task")
        logger.debug(f"响应: intent_type={intent_type}", indent=1)

        if intent_type == "task" and result.get("needs_clarification"):
            logger.debug("响应: 需求不够明确，需要澄清", indent=1)

        return result

    def _execute_internal_tools(self, tools_needed: list) -> list[str]:
        """
        统一执行内部工具调用。
        无论 intent_type 是什么，工具执行都在这里完成。
        """
        logger.debug(f"执行内部工具: {tools_needed}", indent=1)

        results = []
        for tool_call in tools_needed:
            if isinstance(tool_call, str):
                tool_name = tool_call
                tool_params = {}
            elif isinstance(tool_call, dict):
                tool_name = tool_call.get("name", "")
                tool_params = tool_call.get("params", {})
            else:
                continue

            result = self.internal_tools.call(tool_name, tool_params)
            results.append(f"### {tool_name} 执行结果\n\n{result}")

        return results

    def _chat_with_tools_loop(self, user_input: str, initial_context: str, max_rounds: int = 5) -> str:
        """
        多轮工具调用循环。
        LLM 看到工具结果后，可以决定继续调用更多工具（如先 read 再 write），
        直到给出最终文本回复。
        """
        context = initial_context
        
        for round_num in range(max_rounds):
            logger.debug(f"工具循环 第{round_num + 1}轮", indent=1)
            
            messages = [
                {"role": "system", "content": """你是多Agent工作台的智能助手。根据工具执行结果，帮助用户完成请求。

如果你还需要执行更多操作（如修改文件），请返回 JSON：
{"reply": "简短说明你在做什么", "tools_needed": [{"name": "工具名", "params": {...}}]}

如果已经完成，直接返回 JSON：
{"reply": "最终回复内容", "tools_needed": []}"""},
                {"role": "user", "content": f"""用户请求: "{user_input}"

工具执行结果:

{context}

请决定：是否需要继续调用工具？还是可以直接回复用户？"""},
            ]
            
            try:
                result = self.llm_client.call_json(messages, role="orchestrator", temperature=0.3)
            except (ValueError, Exception):
                # JSON 解析失败 → 尝试纯文本回复
                reply = self.llm_client.call(messages, role="orchestrator", temperature=0.5)
                return reply
            
            next_tools = result.get("tools_needed", [])
            reply = result.get("reply", "")
            
            if not next_tools:
                # 没有更多工具调用 → 返回最终回复
                return reply
            
            # 还有工具要调 → 执行并继续循环
            logger.debug(f"继续调用工具: {next_tools}", indent=1)
            new_results = self._execute_internal_tools(next_tools)
            context += "\n\n---\n\n" + "\n\n---\n\n".join(new_results)
        
        # 超过最大轮数 → 返回最后的回复
        return reply or context

    def _clarify(self, intent_result: dict) -> str:
        """多轮澄清对话"""
        questions = intent_result.get("clarification_questions", [])

        console.print()
        console.print(Panel(
            "[bold yellow]💬 需求澄清[/bold yellow]\n"
            "我需要了解更多细节以便更好地完成任务：",
            border_style="yellow",
        ))

        for i, q in enumerate(questions, 1):
            console.print(f"\n[yellow]{i}. {q}[/yellow]")

        console.print()
        answer = Prompt.ask("[bold green]你的回答[/bold green]")

        # 拼合原始请求和澄清后的信息
        enriched_request = f"{self.user_request}\n\n补充信息: {answer}"
        logger.info("需求澄清完成")
        return enriched_request

    def _generate_plan(self, user_input: str) -> dict:
        """生成结构化执行计划"""
        logger.info("Orchestrator 生成执行计划")

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"""用户需求: "{user_input}"

请生成一个结构化的执行计划，严格遵循以下JSON格式：
{{
  "goal": "任务目标",
  "steps": [
    {{
      "step_id": 1,
      "description": "步骤描述",
      "agent": "agent名称 (web_search/analysis/writing/interview)",
      "input": {{}},
      "depends_on": [],
      "pause_after": false
    }}
  ]
}}

注意：
- agent名称必须是当前已注册的: {', '.join(self.agent_registry.list_agents())}
- depends_on 用步骤ID表示依赖关系
- 关键分析/汇总步骤设 pause_after=true
- input 中的参数要符合对应Agent的input_schema
- 如果引用前序步骤结果，在 input 中添加 "source_steps": [step_id_list]"""},
        ]

        plan = self.llm_client.call_json(messages, role="orchestrator", temperature=0.3)

        steps = plan.get("steps", [])
        logger.debug(f"计划包含 {len(steps)} 个步骤", indent=1)

        return plan

    def _confirm_plan(self, plan: dict) -> bool:
        """展示计划，等待用户确认"""
        logger.info("展示计划，等待用户确认")

        # Agent图标映射
        agent_icons = {
            "web_search": "🔍 搜索",
            "analysis": "📊 分析",
            "writing": "📝 撰写",
            "interview": "🎤 访谈",
        }

        console.print()
        console.print("═" * 50, style="bold")
        console.print(f"🎯 [bold]任务：{plan.get('goal', '未知')}[/bold]")
        console.print("═" * 50, style="bold")
        console.print("📋 [bold]执行计划：[/bold]")

        for step in plan.get("steps", []):
            agent = step.get("agent", "unknown")
            icon_label = agent_icons.get(agent, f"❓ {agent}")
            desc = step.get("description", "")
            pause = " ⏸️" if step.get("pause_after") else ""
            deps = step.get("depends_on", [])
            dep_str = f"  (依赖: Step {', '.join(map(str, deps))})" if deps else ""

            console.print(
                f"  Step {step['step_id']}  [{icon_label}] {desc}{pause}{dep_str}"
            )

        console.print("═" * 50, style="bold")
        console.print("[dim]⏸️ = 该步骤完成后暂停让你确认[/dim]")
        console.print()

        choice = Prompt.ask(
            "[bold]确认执行(y) / 修改计划(e) / 取消(q)[/bold]",
            choices=["y", "e", "q"],
            default="y",
        )

        if choice == "y":
            return True
        elif choice == "q":
            return False
        else:
            # 修改计划
            modification = Prompt.ask("[bold green]请描述你想要的修改[/bold green]")
            return self._modify_and_confirm_plan(plan, modification)

    def _modify_and_confirm_plan(self, old_plan: dict, modification: str) -> bool:
        """根据用户反馈修改计划"""
        logger.info(f"用户要求修改计划: {modification}")

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"""原计划:
{json.dumps(old_plan, ensure_ascii=False, indent=2)}

用户反馈: {modification}

请根据用户反馈修改计划，输出新的JSON格式计划。"""},
        ]

        new_plan = self.llm_client.call_json(messages, role="orchestrator", temperature=0.3)
        self.plan = new_plan
        return self._confirm_plan(new_plan)

    def _execute_plan(self, plan: dict):
        """按依赖关系逐步执行计划"""
        steps = plan.get("steps", [])
        total = len(steps)
        completed = set()

        while len(completed) < total:
            # 找到所有依赖已满足、尚未完成的步骤
            ready_steps = [
                s for s in steps
                if s["step_id"] not in completed
                and all(dep in completed for dep in s.get("depends_on", []))
            ]

            if not ready_steps:
                logger.error("死锁：没有可执行的步骤")
                break

            for step in ready_steps:
                step_id = step["step_id"]
                agent_name = step.get("agent", "")
                desc = step.get("description", "")

                console.print(f"\n▶ Step {step_id}/{total} [{agent_name}] {desc}...")

                logger.info(f"开始执行 Step {step_id}/{total}")
                logger.debug(f"├─ Agent: {agent_name}", indent=1)
                logger.debug(f"├─ 输入: {json.dumps(step.get('input', {}), ensure_ascii=False)}", indent=1)

                try:
                    # 组装上下文
                    context = self._assemble_context(step)

                    # 获取Agent并执行
                    agent = self.agent_registry.get_agent(agent_name)
                    step_start = time.time()
                    result = agent.execute(step.get("input", {}), context)
                    step_elapsed = time.time() - step_start

                    self.step_results[step_id] = result
                    completed.add(step_id)

                    logger.info(f"✅ Step {step_id} 完成 (耗时{step_elapsed:.1f}s)")
                    console.print(f"  ✅ 完成 (耗时{step_elapsed:.1f}s)")

                    # 评估结果质量
                    evaluation = self._evaluate_result(step, result, plan)
                    if evaluation.get("needs_extra_step"):
                        self._insert_extra_step(plan, evaluation, step_id)

                except Exception as e:
                    logger.error(f"Step {step_id} 执行失败: {e}")
                    console.print(f"  ❌ 失败: {e}", style="red")

                    # 用户选择
                    choice = Prompt.ask(
                        "[bold]重试(r) / 跳过(s) / 终止(q)[/bold]",
                        choices=["r", "s", "q"],
                        default="r",
                    )
                    if choice == "r":
                        continue  # 重试
                    elif choice == "s":
                        self.step_results[step_id] = f"[跳过] {e}"
                        completed.add(step_id)
                    else:
                        logger.info("用户终止执行")
                        return

                # 暂停点
                if step.get("pause_after") and step_id in completed:
                    self._pause_checkpoint(step, result)

    def _assemble_context(self, step: dict) -> str:
        """组装上下文：将 depends_on 步骤的输出拼入"""
        depends_on = step.get("depends_on", [])
        source_steps = step.get("input", {}).get("source_steps", [])

        # 合并依赖和显式引用
        all_deps = sorted(set(depends_on + source_steps))

        if not all_deps:
            return ""

        parts = []
        for dep_id in all_deps:
            if dep_id in self.step_results:
                parts.append(f"## Step {dep_id} 的输出\n\n{self.step_results[dep_id]}")

        context = "\n\n---\n\n".join(parts)
        logger.debug(
            f"├─ 组装上下文: {len(all_deps)}个依赖步骤, {len(context)}字符",
            indent=1,
        )
        return context

    def _evaluate_result(self, step: dict, result: str, plan: dict) -> dict:
        """评估步骤结果质量"""
        # 简化评估：只对搜索结果做质量检查
        if step.get("agent") != "web_search":
            return {"quality": "good"}

        messages = [
            {"role": "system", "content": "你是一个结果质量评估器。"},
            {"role": "user", "content": f"""评估以下搜索结果的质量：

步骤描述: {step.get('description', '')}
搜索结果:
{result[:2000]}

以JSON格式回答：
{{
  "quality": "good/fair/poor",
  "issues": "问题描述（如果有）",
  "needs_extra_step": false,
  "extra_step_suggestion": "建议的补充步骤（如果需要）"
}}"""},
        ]

        try:
            evaluation = self.llm_client.call_json(messages, role="orchestrator", temperature=0.3)
            if evaluation.get("quality") == "poor":
                logger.warning(f"评估结论: {evaluation.get('issues', '结果质量不佳')}")
            return evaluation
        except Exception:
            return {"quality": "unknown"}

    def _insert_extra_step(self, plan: dict, evaluation: dict, after_step_id: int):
        """动态插入补充步骤"""
        suggestion = evaluation.get("extra_step_suggestion", "")
        if not suggestion:
            return

        steps = plan.get("steps", [])
        new_step_id = after_step_id + 0.5  # 使用小数避免和已有步骤冲突

        # 实际实现中需要重排步骤ID，这里简化处理
        logger.info(f"Orchestrator 决定调整计划")
        logger.debug(f"└─ 插入新步骤: Step {new_step_id} {suggestion}", indent=1)

        console.print(
            f"\n[yellow]📌 计划调整：在 Step {after_step_id} 后插入补充步骤: {suggestion}[/yellow]"
        )

    def _pause_checkpoint(self, step: dict, result: str):
        """暂停检查点"""
        step_id = step["step_id"]
        logger.info(f"⏸️ 暂停点 - Step {step_id} 完成，等待用户确认")

        console.print()
        console.print(Panel(
            f"[bold yellow]⏸️ 阶段检查 — Step {step_id} 完成[/bold yellow]",
            border_style="yellow",
        ))

        # 展示结果摘要（限制长度）
        display_result = result[:1500] + "..." if len(result) > 1500 else result
        console.print(display_result)
        console.print()

        choice = Prompt.ask(
            "[bold]继续(y) / 调整方向(e) / 终止(q)[/bold]",
            choices=["y", "e", "q"],
            default="y",
        )

        if choice == "e":
            feedback = Prompt.ask("[bold green]请描述调整方向[/bold green]")
            logger.info(f"用户调整方向: {feedback}")
            # TODO: 根据反馈重新规划后续步骤
            console.print("[yellow]已记录，继续执行...[/yellow]")
        elif choice == "q":
            logger.info("用户终止执行")
            raise KeyboardInterrupt("用户终止")

        logger.info("用户确认继续")

    def _summarize_results(self, plan: dict) -> str:
        """汇总所有步骤结果"""
        logger.info("所有步骤执行完成")
        logger.info("Orchestrator 汇总结果")

        all_outputs = "\n\n---\n\n".join(
            f"## Step {sid} 的输出\n\n{result}"
            for sid, result in sorted(self.step_results.items())
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"""任务目标: {plan.get('goal', '')}

各步骤的输出如下：

{all_outputs}

请整合所有步骤的结果，生成最终的、用户友好的交付物。
如果结果是文档类，直接输出完整文档。
如果结果是报告类，整合为完整报告。
确保输出完整、专业、可直接使用。"""},
        ]

        return self.llm_client.call(messages, role="orchestrator")

    def _deliver_result(self, final_result: str):
        """展示并保存最终结果"""
        console.print()
        console.print("═" * 50, style="bold green")
        console.print("✅ [bold green]任务完成！以下是最终结果：[/bold green]")
        console.print("═" * 50, style="bold green")
        console.print()
        console.print(final_result)
        console.print()

        # 保存到文件
        output_dir = self.config.output_dir
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"{self.task_id}.md")

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"# {self.plan.get('goal', '任务结果')}\n\n")
            f.write(final_result)

        console.print(f"[dim]结果已保存到: {output_file}[/dim]")
        logger.info(f"结果已保存: {output_file}")
