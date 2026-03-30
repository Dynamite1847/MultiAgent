"""
AgentState — Agent Loop 的完整状态，可序列化、可持久化。

每次 SSE 流中 Agent 状态发生变化时，自动保存到 session 文件中。
服务重启后可以从 session 恢复状态。
"""
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class AgentState:
    """Agent 循环的完整状态"""

    session_id: str = ""
    messages: list[dict] = field(default_factory=list)
    pending_tool_calls: list[dict] = field(default_factory=list)
    status: str = "idle"  # idle | thinking | executing | awaiting_confirm | done
    turn_count: int = 0
    max_turns: int = 25
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)

    # 累计统计
    total_tool_calls: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict:
        """序列化为字典"""
        self.last_updated = time.time()
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AgentState":
        """从字典反序列化"""
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    def add_user_message(self, content: str):
        """添加用户消息"""
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str, tool_calls: list = None):
        """添加助手消息"""
        msg = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.messages.append(msg)

    def add_tool_result(self, tool_call_id: str, content: str):
        """添加工具结果"""
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        })

    def estimate_tokens(self) -> int:
        """估算当前 messages 的 token 数（字符数 / 4）"""
        total_chars = sum(len(str(m.get("content", ""))) for m in self.messages)
        # tool_calls 中的参数也算
        for m in self.messages:
            if "tool_calls" in m:
                for tc in m["tool_calls"]:
                    fn = tc.get("function", {})
                    total_chars += len(str(fn.get("arguments", "")))
        return total_chars // 4

    def is_over_limit(self, context_limit: int, threshold: float = 0.85) -> bool:
        """是否超过上下文限制的阈值"""
        return self.estimate_tokens() > int(context_limit * threshold)
