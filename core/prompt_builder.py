"""
Prompt Builder - 根据注册的 Agent 动态生成 Orchestrator 的 System Prompt
"""
from datetime import datetime
from core.logger import logger

# Orchestrator 精简系统提示词
ORCHESTRATOR_SYSTEM_PROMPT = """你是多 Agent 工作台的主控 Agent（Orchestrator）。

## 当前时间
{current_time}

## 你的核心职责
1. 理解用户需求，判断信息是否完整
2. 信息不完整时**主动追问**，绝不猜测
3. 信息完整时，生成执行计划并调度子 Agent 执行
4. 评估每步结果质量，汇总生成最终交付物

## 你自己不做具体工作，只分配给子 Agent。

{agent_section}

{tools_section}
"""


def build_orchestrator_prompt(
    agent_manifests: dict[str, dict],
    internal_tool_defs: list[dict] = None,
) -> str:
    """
    根据当前注册的 Agent 和内部工具动态生成 Orchestrator 的完整 System Prompt
    """
    # Agent 概述
    agent_section = f"## 可用的子 Agent（共 {len(agent_manifests)} 个）\n\n"
    for idx, (name, manifest) in enumerate(agent_manifests.items(), 1):
        display_name = manifest.get("display_name", name)
        description = manifest.get("description", "")
        agent_section += f"- **{name}**（{display_name}）: {description}\n"
    agent_section += "\n每个 Agent 的详细参数 Schema 会在生成执行计划时自动注入。"

    # 内部工具
    tools_section = ""
    if internal_tool_defs:
        tools_section = f"\n## 内部工具（共 {len(internal_tool_defs)} 个）\n\n"
        for tool_def in internal_tool_defs:
            name = tool_def.get("name", "")
            desc = tool_def.get("description", "")
            tools_section += f"- **{name}**: {desc}\n"

    # 拼装
    full_prompt = ORCHESTRATOR_SYSTEM_PROMPT.format(
        current_time=datetime.now().strftime("%Y-%m-%d %H:%M (%A)"),
        agent_section=agent_section,
        tools_section=tools_section,
    )

    logger.info("Prompt Builder 生成 Orchestrator System Prompt")
    logger.debug(f"└─ Prompt 长度: {len(full_prompt)} 字符")

    return full_prompt
