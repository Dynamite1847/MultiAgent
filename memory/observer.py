"""
Observer Memory (OM) — 自动上下文管理。

核心原则：
1. Session 文件中的 messages 数组永远保持完整，不删除任何消息
2. 压缩生成的摘要作为独立字段 observer_summary 存储在 session 中
3. 构建 LLM 上下文时，用 [摘要] + [最近 N 轮] 替代完整历史
"""
import time
import re
from typing import Optional
from core.logger import logger


# ── Token 估算 ──────────────────────────────

_CJK_RE = re.compile(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]')


def estimate_tokens(text: str) -> int:
    """快速估算 token 数（CJK ~2字符/token，其他 ~4字符/token）"""
    if not text:
        return 0
    cjk_count = len(_CJK_RE.findall(text))
    other_count = len(text) - cjk_count
    return cjk_count // 2 + other_count // 4 + 1


def estimate_messages_tokens(messages: list[dict]) -> int:
    """估算 messages 数组的总 token 数"""
    total = 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content) + 4  # per-message overhead
        elif isinstance(content, list):
            for part in content:
                if part.get("type") == "text":
                    total += estimate_tokens(part.get("text", ""))
                elif part.get("type") == "image_url":
                    total += 1024
        # tool_calls 参数也计入
        for tc in m.get("tool_calls", []):
            fn = tc.get("function", {})
            total += estimate_tokens(str(fn.get("arguments", "")))
    return total


# ── Observer Memory ──────────────────────────


class ObserverMemory:
    """Observer Memory — 自动上下文压缩。

    不修改原始 messages，只生成摘要。
    调用方决定如何组装上下文。
    """

    # 摘要 prompt 模板
    SUMMARY_PROMPT = (
        "你是一个对话记录员。你的任务是将对话历史转写为详细的结构化记录。\n\n"
        "## 核心原则\n"
        "- **保留细节优先**：宁可记录稍长，也不要遗漏重要信息\n"
        "- **保留具体事实**：数字、名称、日期、具体结论都要保留\n"
        "- **保留对话脉络**：用户提了什么问题、AI给了什么建议、用户做了什么决定\n"
        "- **保留情感和态度**：用户的偏好、担忧、反对意见\n"
        "- **保留推理过程**：重要的分析和论证链条不要省略\n\n"
        "## 需要记录的内容\n"
        "1. 用户的背景信息、个人偏好、明确表达的需求\n"
        "2. 讨论过的每个主题及其具体结论（不要合并不同主题）\n"
        "3. 工具调用的关键发现（保留具体数据点和来源，省略原始HTML/JSON）\n"
        "4. 用户做出的决策及其理由\n"
        "5. 待办事项、未解决的问题、下一步计划\n"
        "6. 用户明确反对或纠正过的内容\n\n"
        "## 增量合并规则（当存在已有历史摘要时）\n"
        "- **已有历史摘要**是之前对话经过精心整理的记录，权重更高，核心内容应当保留\n"
        "- **新增对话**是最新发生的内容，需要合并进已有记录中\n"
        "- 合并时，AI 自主判断：如果旧记录中的某些细节已被新对话推翻或更新，用新内容替换；"
        "否则保留旧记录原文\n"
        "- 最终输出应是一份完整的、合并后的记录，而不是简单拼接\n\n"
        "## 输出格式\n"
        "使用 Markdown，按对话主题分组，每个主题下用嵌套列表记录细节。\n"
        "长度应为原始对话的 50%。这不是摘要而是详细笔记，宁长勿漏。\n\n"
    )

    @staticmethod
    def should_compact(
        messages: list[dict],
        observer_summary: Optional[dict],
        context_limit: int,
        threshold: float = 0.7,
        context_rounds: int = 10,
    ) -> bool:
        """判断是否需要压缩。

        逻辑：
        - 计算 build_context 会产出的 token 量（summary + 活跃窗口）
        - 如果超过 context_limit * threshold → 需要压缩
        - 同时，如果 messages 总数 > context_rounds * 2 + 4 且没有 summary → 也触发
        """
        if not messages:
            return False

        # 已压缩到的位置
        compressed_up_to = 0
        if observer_summary:
            compressed_up_to = observer_summary.get("compressed_up_to", 0)

        # 活跃窗口大小
        active_window_size = context_rounds * 2  # 每轮 2 条 (user + assistant)

        # 防止高频压缩：如果已经压缩到最优边界，没有新消息可压缩
        optimal_boundary = max(len(messages) - active_window_size, 0)
        if compressed_up_to >= optimal_boundary:
            return False

        # 未压缩的消息
        uncompressed = messages[compressed_up_to:]
        uncompressed_tokens = estimate_messages_tokens(uncompressed)

        # summary 本身的 token
        summary_tokens = 0
        if observer_summary and observer_summary.get("content"):
            summary_tokens = estimate_tokens(observer_summary["content"])

        total_context = summary_tokens + uncompressed_tokens

        # 条件1: 上下文超过阈值
        if total_context > int(context_limit * threshold):
            logger.info(f"OM: 上下文 {total_context} tokens 超过阈值 "
                       f"({int(context_limit * threshold)}), 需要压缩")
            return True

        # 条件2: 未压缩消息数远超活跃窗口
        if len(uncompressed) > active_window_size + 6:
            logger.info(f"OM: 未压缩消息 {len(uncompressed)} 条，"
                       f"超过活跃窗口 {active_window_size}+6，建议压缩")
            return True

        return False

    @staticmethod
    def compact(
        messages: list[dict],
        llm_client,
        role: str = "orchestrator",
        existing_summary: Optional[dict] = None,
        context_rounds: int = 10,
    ) -> dict:
        """执行压缩，返回新的 observer_summary 字典。

        不修改 messages 数组。

        Args:
            messages: 完整的消息历史
            llm_client: LLMClient 实例
            role: LLM 角色
            existing_summary: 已有的摘要（增量压缩）
            context_rounds: 保留多少轮不压缩

        Returns:
            {
                "content": "摘要文本...",
                "compressed_up_to": 42,
                "message_count": 50,
                "created_at": "2026-03-30T...",
                "version": 2
            }
        """
        if not messages:
            return existing_summary or {}

        # 确定压缩边界：保留最后 context_rounds 轮
        active_window_size = context_rounds * 2  # user + assistant
        # 至少保留最后 4 条消息不压缩（确保当前对话流畅）
        keep_count = max(active_window_size, 4)

        if len(messages) <= keep_count:
            logger.info("OM: 消息数不足，无需压缩")
            return existing_summary or {}

        compress_boundary = len(messages) - keep_count

        # 构建要压缩的内容
        to_compress = messages[:compress_boundary]

        # 如果已有摘要，增量压缩（只处理上次压缩后到本次边界的新消息）
        prev_compressed_up_to = 0
        if existing_summary:
            prev_compressed_up_to = existing_summary.get("compressed_up_to", 0)

        # 只需要压缩 prev_compressed_up_to → compress_boundary 之间的新消息
        new_messages = messages[prev_compressed_up_to:compress_boundary]

        if not new_messages:
            logger.info("OM: 没有新消息需要压缩")
            return existing_summary or {}

        # 构建压缩 prompt
        parts = [ObserverMemory.SUMMARY_PROMPT]

        if existing_summary and existing_summary.get("content"):
            parts.append(f"--- 已有的历史摘要 ---\n{existing_summary['content']}\n\n")

        parts.append("--- 需要压缩的新对话 ---\n\n")

        for m in new_messages:
            role_label = m.get("role", "?")
            content = m.get("content", "")
            if isinstance(content, list):
                # 多模态消息，提取文本部分
                text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
                content = "\n".join(text_parts)
            if role_label == "tool":
                content = content[:2000]  # 工具结果适当截断
            # 非工具消息不截断，保留完整内容
            parts.append(f"[{role_label}] {content}\n\n")

        compress_prompt = "".join(parts)

        # Version counter
        version = 1
        if existing_summary:
            version = existing_summary.get("version", 1) + 1

        logger.info(f"OM: 压缩 {len(new_messages)} 条新消息 "
                   f"(边界: {prev_compressed_up_to}→{compress_boundary}, "
                   f"version={version})")

        try:
            summary_text = llm_client.call(
                [{"role": "user", "content": compress_prompt}],
                role=role,
                temperature=0.3,
                max_tokens=8192,  # 给足空间，确保详细记录不被截断
            )

            result = {
                "content": summary_text,
                "compressed_up_to": compress_boundary,
                "message_count": len(messages),
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "version": version,
            }

            logger.info(f"OM: 压缩完成，摘要 {estimate_tokens(summary_text)} tokens, "
                       f"compressed_up_to={compress_boundary}")

            return result

        except Exception as e:
            logger.error(f"OM: 压缩失败: {e}")
            return existing_summary or {}

    @staticmethod
    def build_context(
        messages: list[dict],
        observer_summary: Optional[dict] = None,
        context_rounds: int = 10,
    ) -> list[dict]:
        """构建 LLM 上下文。

        返回：[摘要消息(如果有)] + [最近的消息]

        Args:
            messages: 完整的消息历史
            observer_summary: OM 摘要
            context_rounds: 活跃窗口大小

        Returns:
            用于 LLM 调用的 messages 列表
        """
        result = []

        # 确定活跃窗口
        active_window_size = context_rounds * 2  # user + assistant

        if observer_summary and observer_summary.get("content"):
            compressed_up_to = observer_summary.get("compressed_up_to", 0)
            summary_content = observer_summary["content"]

            # 摘要作为上下文注入
            result.append({
                "role": "user",
                "content": f"[以下是之前对话的摘要，帮助你理解上下文]\n\n{summary_content}"
            })
            result.append({
                "role": "assistant",
                "content": "好的，我已了解之前的对话上下文，请继续。"
            })

            # 未压缩的消息
            recent = messages[compressed_up_to:]
        else:
            # 没有摘要，从完整历史中取最近的
            recent = messages

        # 限制活跃窗口大小
        if len(recent) > active_window_size:
            recent = recent[-active_window_size:]

        # 过滤：只保留 user/assistant/tool 角色
        for m in recent:
            role = m.get("role", "")
            if role in ("user", "assistant", "tool"):
                result.append(m)

        logger.debug(f"OM build_context: summary={'有' if observer_summary else '无'}, "
                    f"活跃消息={len(recent)}, 总上下文={len(result)} 条")

        return result
