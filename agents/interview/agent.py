"""
InterviewAgent - 用户访谈Agent（Web 兼容版：通过 need_input 协议与用户多轮对话）
"""
import json
from agents.base import BaseAgent
from core.logger import logger


class InterviewAgent(BaseAgent):
    """
    用户访谈Agent：通过 need_input 返回值暂停工作流，与用户进行多轮对话。
    
    执行流程：
    1. 首次调用（无 user_answer）→ 生成开场白+首轮问题 → 返回 need_input
    2. 后续调用（有 user_answer）→ 基于对话历史追问 → 返回 need_input
    3. 当所有主题聊完 → 生成摘要 → 返回正常字符串
    """

    def execute(self, input_data: dict, context: str = "") -> str:
        topics = input_data.get("topics", [])
        if not topics:
            return "错误：未提供访谈主题"

        user_answer = input_data.get("user_answer", "")
        agent_state = input_data.get("_agent_state", {})
        conversation_history = agent_state.get("conversation_history", [])
        round_num = agent_state.get("round_num", 0)

        logger.info(f"InterviewAgent 执行 (主题: {', '.join(topics)}, round: {round_num})")

        # ── 首次调用：生成开场白 ──
        if not user_answer:
            opening_prompt = f"""根据以下访谈主题，生成开场白和首轮问题。

## 访谈主题
{chr(10).join(f'- {t}' for t in topics)}

请输出：
1. 简短的开场白（1-2句话）
2. 针对第一个主题的2-3个提问

注意：你是共创伙伴，提问要有针对性，帮助用户厘清想法。
"""
            messages = self._build_messages(opening_prompt, context)
            opening = self.llm_client.call(messages, role=self.name)

            return json.dumps({
                "type": "need_input",
                "message": opening,
                "questions": [opening],
                "state": {
                    "conversation_history": [],
                    "round_num": 0,
                    "topics": topics,
                    "llm_messages": messages + [{"role": "assistant", "content": opening}],
                },
            }, ensure_ascii=False)

        # ── 用户回答了"结束" ──
        if user_answer.strip().lower() in ("done", "结束", "exit", "quit", "完成"):
            return self._generate_summary(topics, conversation_history, context)

        # ── 后续轮次：基于历史追问 ──
        round_num += 1
        conversation_history.append({"role": "user_answer", "content": user_answer})

        # 恢复 LLM 对话上下文
        llm_messages = agent_state.get("llm_messages", [])
        if not llm_messages:
            llm_messages = self._build_messages(
                f"访谈主题: {', '.join(topics)}", context
            )
        llm_messages.append({"role": "user", "content": user_answer})

        follow_up_prompt = (
            "根据用户的回答，继续深入提问。"
            "如果当前主题已经聊清楚了，进入下一个主题。"
            '如果所有主题都聊完了，告诉用户可以输入「结束」来完成访谈。'
            "每次提2-3个问题。"
        )
        llm_messages.append({"role": "user", "content": follow_up_prompt})

        follow_up = self.llm_client.call(llm_messages, role=self.name)
        llm_messages.append({"role": "assistant", "content": follow_up})
        conversation_history.append({"role": "agent", "content": follow_up})

        # 检查是否可以自动结束（超过合理轮数）
        if round_num >= 10:
            return self._generate_summary(topics, conversation_history, context)

        return json.dumps({
            "type": "need_input",
            "message": follow_up,
            "questions": [follow_up],
            "state": {
                "conversation_history": conversation_history,
                "round_num": round_num,
                "topics": topics,
                "llm_messages": llm_messages,
            },
        }, ensure_ascii=False)

    def _generate_summary(self, topics: list, conversation_history: list, context: str) -> str:
        """生成访谈摘要（正常字符串返回，而非 need_input）"""
        if not conversation_history:
            return "访谈未进行任何对话。"

        formatted = self._format_conversation(conversation_history)

        summary_prompt = f"""请根据以下访谈记录，生成结构化的访谈摘要。

## 访谈主题
{chr(10).join(f'- {t}' for t in topics)}

## 对话记录
{formatted}

请输出结构化摘要，包含：
1. 每个主题的关键结论
2. 用户的核心诉求
3. 待进一步确认的问题
4. 访谈中发现的关键洞察
"""
        messages = self._build_messages(summary_prompt, context)
        summary = self.llm_client.call(messages, role=self.name)
        logger.info(f"InterviewAgent 完成 (共{len(conversation_history)}条记录)")
        return summary

    def _format_conversation(self, history: list[dict]) -> str:
        """格式化对话记录"""
        parts = []
        for item in history:
            role = "用户" if item["role"] == "user_answer" else "Agent"
            parts.append(f"**{role}**: {item['content']}")
        return "\n\n".join(parts)
