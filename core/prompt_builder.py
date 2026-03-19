"""
Prompt Builder - 根据注册的 Agent 动态生成 Orchestrator 的 System Prompt
"""
from datetime import datetime
from core.logger import logger

# Orchestrator 的固定 Prompt 部分
ORCHESTRATOR_PROMPT_HEADER = """你是多Agent工作台的主控Agent（Orchestrator）。

## 当前时间
{current_time}

## 你的职责
- 理解用户的自然语言需求
- **首先判断用户输入是否是一个真正的工作任务**
- 对于工作任务：判断是否足够清晰 → 不清晰则追问 → 生成执行计划
- 对于非工作任务（闲聊、打招呼、问系统功能等）：直接友好回复
- 调度子Agent执行具体工作
- 评估每步结果的质量，必要时动态调整计划
- 汇总所有结果，生成最终交付物

## 你自己不做具体工作，只分配给子Agent。

"""

ORCHESTRATOR_PROMPT_FOOTER = """
## 规则

### 意图理解阶段（最重要）
当收到用户输入时，你**必须首先判断 intent_type**：

1. **"task"** — 用户提出了一个具体的工作任务（如写PRD、调研竞品、分析需求等）
   - 继续判断需求是否明确，然后生成执行计划
2. **"chat"** — 用户在闲聊、打招呼、问问题、感谢、表达情绪等
   - 直接给出友好回复，不要生成执行计划
3. **"system_command"** — 用户想执行系统操作（退出、切换模型、查看状态等）
   - 识别出具体的系统指令
4. **"unclear"** — 用户说了些什么但你无法判断意图
   - 友好地追问用户想做什么

**判断示例**：
- "帮我调研一下Cursor" → task
- "你好" / "谢谢" / "你能做什么" → chat
- "退出" / "结束" / "关闭" → system_command
- "嗯" / "..." → unclear

### 执行计划格式
你必须输出严格的 JSON 格式执行计划：
```json
{
  "goal": "任务目标描述",
  "steps": [
    {
      "step_id": 1,
      "description": "步骤描述",
      "agent": "agent名称",
      "input": {
        "根据agent的input_schema填写"
      },
      "depends_on": [],
      "pause_after": false
    }
  ]
}
```

### 计划规则
- depends_on: 该步骤依赖哪些前序步骤（用step_id列表表示）
- pause_after: 设为true表示该步骤完成后暂停让用户确认
- 没有依赖关系的步骤可以标记为并行执行
- 关键的分析/总结步骤建议设置 pause_after=true
- 合理安排步骤顺序：先搜集信息，再分析，最后生成文档
- 如果任务涉及用户细节确认（如产品中的具体场景、使用习惯、偏好等），应考虑使用 interview agent

### 结果评估
每步执行完成后，你会收到执行结果。你需要：
1. 评估结果质量是否满足需求
2. 如果信息不足，可以决定插入新步骤
3. 如果方向偏离，可以修改后续步骤
4. 将评估结论作为 JSON 返回

### 结果汇总
所有步骤完成后，整合全部输出，生成一段用户友好的总结。
"""


def build_orchestrator_prompt(
    agent_manifests: dict[str, dict],
    internal_tool_defs: list[dict] = None,
) -> str:
    """
    根据当前注册的 Agent 和内部工具动态生成 Orchestrator 的完整 System Prompt
    
    Args:
        agent_manifests: {agent_name: manifest_dict}
        internal_tool_defs: 内部工具定义列表
    
    Returns:
        完整的 system prompt 字符串
    """
    # 动态部分：可用的子Agent列表
    agent_section = f"## 当前可用的子Agent（共{len(agent_manifests)}个）\n\n"

    for idx, (name, manifest) in enumerate(agent_manifests.items(), 1):
        display_name = manifest.get("display_name", name)
        description = manifest.get("description", "")
        when_to_use = manifest.get("when_to_use", "")
        input_schema = manifest.get("input_schema", {})

        agent_section += f"### {idx}. [{name}] {display_name}\n"
        agent_section += f"**描述**: {description}\n"
        agent_section += f"**适用场景**:\n{when_to_use}\n"

        # 输入参数
        if input_schema:
            agent_section += "**输入参数**:\n"
            for param_name, param_info in input_schema.items():
                param_type = param_info.get("type", "string")
                param_desc = param_info.get("description", "")
                required = param_info.get("required", False)
                req_tag = " (必填)" if required else " (可选)"
                agent_section += f"  - `{param_name}` ({param_type}){req_tag}: {param_desc}\n"

        agent_section += "\n"

    # 内部工具部分
    tools_section = ""
    if internal_tool_defs:
        tools_section = f"\n## 内部工具（共{len(internal_tool_defs)}个）\n\n"
        tools_section += "你可以在 tools_needed 字段中指定需要调用的工具来获取信息或执行操作。\n\n"
        for tool_def in internal_tool_defs:
            name = tool_def.get("name", "")
            desc = tool_def.get("description", "")
            params = tool_def.get("parameters", {})
            tools_section += f"- **{name}**: {desc}\n"
            if params:
                for p_name, p_desc in params.items():
                    tools_section += f"  - 参数 `{p_name}`: {p_desc}\n"
        tools_section += "\n"

    # 拼装完整 prompt（注入当前时间）
    header = ORCHESTRATOR_PROMPT_HEADER.format(
        current_time=datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
    )
    full_prompt = header + agent_section + tools_section + ORCHESTRATOR_PROMPT_FOOTER

    logger.info("Prompt Builder 生成Orchestrator System Prompt")
    logger.debug(f"└─ Prompt长度: {len(full_prompt)} 字符")

    return full_prompt
