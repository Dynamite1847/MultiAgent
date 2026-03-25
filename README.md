# 🤖 Multi-Agent Workbench

Multi-Agent 智能工作台是一个强大的 AI 协作平台，支持通过自然语言驱动多个专业领域 AI Agent 协作流来自动完成复杂任务，同时也提供纯粹的多模态聊天功能。项目提供现代化的 React Web 界面以及基于 FastAPI 的流式响应后端。

![Workbench UI](./frontend/public/favicon.ico) <!-- Placeholder for actual screenshots -->

## ✨ 核心特性

- **双引擎模式** 
  - 🧠 `Agent 模式`：由 Orchestrator（编排器）驱动，自动理解意图、规划步骤（生成执行计划）、并调度子 Agent 分步完成复杂工作。
  - 💬 `对话模式`：纯粹的增强型多模态聊天，支持上传文档（PDF、Word等）和图片与 AI 交流。
- **工作流逐步审查 (Step-by-Step Review)** —— 在运行 Agent 工作流时，可以自动在此步骤悬停审查。支持：`继续执行`、`重试当前步`、`人工干预编辑结果`。
- **现代化体验 (Web UI)**
  - 流式打字机输出（SSE）
  - 会话管理（自动生成标题、每会话独立记忆其 Agent/Chat 模式）
  - 侧边栏参数面板（热切换模型、自定义 Prompt、温度调节等）
- **多模型 & 多提供商支持** —— 开箱即用支持 Anthropic, DeepSeek, 阿里百炼(DashScope), 字节豆包(Doubao), Google Gemini, OpenAI 等。
- **可拓展的插件架构** —— 新增Agent 或 工具只需添加对应目录，系统会自动注册。内置 `tavily_search` 等工具以及沙箱文件读写（沙箱环境）。

## 🏗️ 架构概览

```text
[ 前端 React + Vite ] <== Server-Sent Events (SSE) ==> [ 后端 FastAPI ]
                                                              │
后端分层：                                                     │
1. Server.py - 路由，会话，持久化，状态机                           │
2. Orchestrator - 意图理解 → 规划 → 调度 → 汇总                    │
3. Agent Registry - 子调度节点（WebSearch, Analysis, Writing 等） │
4. Tool Registry - 内部系统与外部API工具（Tavily, SandboxIO等）    │
5. LLM Client - 统一封装的多 Provider LLM 适配器                   │
```

## 🚀 快速开始

### 1. 环境准备

项目后端使用 Python 3.11+，前端使用 Node.js。建议使用 Conda 隔离环境：

```bash
# 1. 创建 Python 环境
conda create -n multiagent python=3.11 -y
conda activate multiagent
pip install -r requirements.txt

# 2. 安装前端依赖
cd frontend
npm install
cd ..
```

### 2. 配置 API Key

系统依赖大模型 API，同时也依赖搜索 API（默认需要 Tavily 搜索）：

```bash
# 从模板复制环境变量并填入你的 Key
cp .env.example .env
```
*(注意：请确保至少配置了一个你想使用的大模型 Provider 的 API Key)*

### 3. 一键启动

我们提供了一个启动脚本来同时拉起后端的 FastAPI 和前端的 Vite 服务：

```bash
# 添加执行权限（仅首次需执行）
chmod +x start.sh

# 启动服务
./start.sh start
```
- 前端地址：`http://localhost:3000`
- 后端 API：`http://localhost:9000`

要停止或重启服务：
```bash
./start.sh stop
./start.sh restart
```

## ⚙️ 系统配置 (`config.yaml`)

项目核心系统配置均在 `config.yaml` 中，支持热重载（无需重启服务即可生效）：

- **Provider & Model 注册**：预置了各大模型厂商的模型名和基准参数。你可以随时添加对应的新模型。
- **默认 Agent 关联 (`role_models`)**：可以分别指派 Orchestrator、Writing、Search 等使用不同的大模型（例如 Orchestrator 使用更强的模型，而 Search 侧使用更快便宜的模型）。
- **运行参数 (`default_params`)**：对话轮数上限（防止 Token 爆表）、Temperature 控制等。

## 🧩 添加新的子 Agent

系统基于松耦合架构设计。只需要 3 步即可新增属于你的专业 Agent：
1. 在 `agents/` 下新建一个目录（如 `agents/coder/`）。
2. 在目录下添加 `manifest.yaml` (定义输入输出类型和工具权限)。
3. 在目录下添加 `agent.py`，继承 `BaseAgent` 并在 `execute()` 中实现你的 Agent 逻辑；配套写上你的 `prompts.md` 调优即可。

重启服务后，Orchestrator 将自动发现你的新 Agent 并能编排它！

## 📄 License
MIT
