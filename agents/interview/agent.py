"""
InterviewAgent - 用户访谈Agent（特殊Agent：暂停工作流与用户多轮对话）
"""
from agents.base import BaseAgent
from core.logger import logger
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

console = Console()


class InterviewAgent(BaseAgent):
    """
    用户访谈Agent：暂停工作流，与用户进行多轮对话。
    这是唯一需要用户直接参与的Agent。
    """

    def execute(self, input_data: dict, context: str = "") -> str:
        topics = input_data.get("topics", [])
        if not topics:
            return "错误：未提供访谈主题"

        logger.info(f"InterviewAgent 开始执行 (主题: {', '.join(topics)})")

        # 1. 生成访谈提纲
        opening_prompt = f"""根据以下访谈主题，生成开场白和第一轮问题。

## 访谈主题
{chr(10).join(f'- {t}' for t in topics)}

请输出：
1. 简短的开场白（1-2句话）
2. 针对第一个主题的2-3个提问

注意：你是共创伙伴，提问要有针对性，帮助用户厘清想法。
"""
        messages = self._build_messages(opening_prompt, context)
        opening = self.llm_client.call(messages, role=self.name)

        # 2. 与用户多轮对话
        conversation_history = []
        conversation_messages = list(messages)  # 完整消息历史
        conversation_messages.append({"role": "assistant", "content": opening})

        console.print()
        console.print(Panel(
            f"[bold cyan]🎤 用户访谈[/bold cyan]\n主题: {', '.join(topics)}",
            border_style="cyan",
        ))
        console.print()
        console.print(f"[cyan]{opening}[/cyan]")
        console.print()
        console.print("[dim]提示: 输入你的回答，输入 'done' 或 '结束' 结束访谈[/dim]")
        console.print()

        round_num = 0
        while True:
            # 用户输入
            user_input = Prompt.ask("[bold green]你的回答[/bold green]")

            if user_input.lower().strip() in ("done", "结束", "exit", "quit"):
                console.print("\n[dim]访谈结束，正在整理摘要...[/dim]\n")
                break

            round_num += 1
            conversation_history.append({"role": "user_answer", "content": user_input})

            # Agent 基于对话历史继续提问
            conversation_messages.append({"role": "user", "content": user_input})

            follow_up_prompt = (
                "根据用户的回答，继续深入提问。"
                "如果当前主题已经聊清楚了，进入下一个主题。"
                "如果所有主题都聊完了，告诉用户可以结束访谈。"
                "每次提2-3个问题。"
            )
            conversation_messages.append({"role": "user", "content": follow_up_prompt})

            follow_up = self.llm_client.call(conversation_messages, role=self.name)
            conversation_messages.append({"role": "assistant", "content": follow_up})

            console.print(f"\n[cyan]{follow_up}[/cyan]\n")

        # 3. 生成访谈摘要
        summary_prompt = f"""请根据以下访谈记录，生成结构化的访谈摘要。

## 访谈主题
{chr(10).join(f'- {t}' for t in topics)}

## 对话记录
{self._format_conversation(conversation_history)}

请输出结构化摘要，包含：
1. 每个主题的关键结论
2. 用户的核心诉求
3. 待进一步确认的问题
4. 访谈中发现的关键洞察
"""
        summary_messages = self._build_messages(summary_prompt, context)
        summary = self.llm_client.call(summary_messages, role=self.name)

        logger.info(f"InterviewAgent 完成 (共{round_num}轮对话)")
        return summary

    def _format_conversation(self, history: list[dict]) -> str:
        """格式化对话记录"""
        parts = []
        for item in history:
            role = "用户" if item["role"] == "user_answer" else "Agent"
            parts.append(f"**{role}**: {item['content']}")
        return "\n\n".join(parts)
