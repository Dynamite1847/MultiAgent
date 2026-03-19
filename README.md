# 🤖 Multi-Agent Workbench

多Agent智能工作台 —— 通过自然语言驱动多个AI Agent协作完成复杂任务。

## ✨ 特性

- **自然语言交互** — 直接告诉系统你想做什么，Orchestrator 自动理解、规划、执行
- **多Agent协作** — WebSearch / Analysis / Writing / Interview 四个子Agent各司其职
- **插件化架构** — 新增Agent只需添加目录 + manifest.yaml，零代码改动
- **多模型支持** — 灵活切换 Doubao / Claude / Gemini / DeepSeek 等 LLM Provider
- **沙箱化工具** — 内置 read_file / write_file / list_directory，安全访问项目文件
- **多轮工具调用** — LLM 可自主决定读取→修改→确认的多步操作
- **对话记忆** — 跨轮次对话历史，支持上下文理解

## 🏗️ 架构

```
用户输入
  ↓
Orchestrator（编排器）
  ├─ 意图理解 → chat / task / system_command
  ├─ 内部工具 → read_file / write_file / list_directory
  ├─ 任务规划 → 生成执行计划（JSON）
  └─ 子Agent调度
       ├─ WebSearchAgent  → Tavily 搜索 + LLM 提炼
       ├─ AnalysisAgent   → 多框架深度分析
       ├─ WritingAgent     → 自动识别文档类型 + 生成
       └─ InterviewAgent   → 多轮共创式访谈
```

## 🚀 快速开始

### 1. 环境准备

```bash
# 创建 Conda 环境
conda create -n multiagent python=3.11 -y
conda activate multiagent

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
# 复制配置模板
cp .env.example .env

# 编辑 .env，填入你的 API Key
# 至少需要一个 Provider 的 Key
```

### 3. 运行

```bash
python main.py
```

### 4. 系统检查

```bash
python main.py --check
```

## 📁 项目结构

```
MultiAgent/
├── main.py                 # CLI 入口
├── config.yaml             # 系统配置（Provider、角色映射、参数）
├── .env                    # API Key（不上传）
│
├── core/                   # 核心框架
│   ├── config.py           # 配置管理
│   ├── llm_client.py       # LLM 统一调用（支持多 Provider/JSON mode）
│   ├── prompt_builder.py   # 动态 System Prompt 生成
│   ├── internal_tools.py   # 沙箱化文件操作工具
│   ├── agent_registry.py   # Agent 自动发现与注册
│   ├── tool_registry.py    # 工具自动发现与注册
│   └── logger.py           # 日志系统
│
├── orchestrator/           # 编排器
│   └── orchestrator.py     # 意图理解 → 规划 → 调度 → 汇总
│
├── agents/                 # 子 Agent（插件式）
│   ├── base.py             # Agent 基类
│   ├── web_search/         # 网络搜索 Agent
│   ├── analysis/           # 分析整合 Agent
│   ├── writing/            # 文档撰写 Agent
│   └── interview/          # 用户访谈 Agent
│
├── tools/                  # 外部工具（插件式）
│   └── tavily_search/      # Tavily 搜索封装
│
└── outputs/                # 任务输出（不上传）
```

## ⚙️ 配置说明

### 模型切换

编辑 `config.yaml` 的 `role_models` 部分：

```yaml
role_models:
  orchestrator: doubao/doubao-seed-2-0-pro-260215
  web_search:   doubao/doubao-seed-2-0-pro-260215
  analysis:     anthropic/claude-opus-4-6-thinking   # 可以按角色分别配置
  writing:      doubao/doubao-seed-2-0-pro-260215
  interview:    doubao/doubao-seed-2-0-pro-260215
```

### 添加新 Agent

1. 在 `agents/` 下创建目录
2. 添加 `manifest.yaml`（定义名称、描述、输入输出）
3. 添加 `agent.py`（继承 `BaseAgent`，实现 `execute()`）
4. 添加 `prompts.md`（System Prompt）
5. 重启即自动注册

## 📄 License

MIT
