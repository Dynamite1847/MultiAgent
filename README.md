# 🤖 Multi-Agent Workbench

一个基于 **Agent Loop 自主循环架构** 的 AI 智能工作台。通过自然语言驱动 AI Agent 自主规划、调用工具并迭代完成复杂任务，同时也提供流畅的多模态聊天体验。

## ✨ 核心特性

### 🧠 Agent Loop 自主循环
- **自主决策**：Agent 根据用户需求自主选择工具，无需人工编排步骤
- **多轮迭代**：每个任务最多 25 轮自动迭代（调用工具 → 分析结果 → 决定下一步），直到任务完成
- **实时可视化**：右侧工作区面板实时展示每一轮的工具调用、参数和结果
- **安全机制**：破坏性操作（写入/删除文件）自动触发人工确认，读取类操作自动执行

### 💬 双引擎模式
| 模式 | 说明 |
|------|------|
| **Agent 模式** | 自主循环，自动调用 Web 搜索、文件读写等工具完成任务 |
| **对话模式** | 纯粹的流式聊天，支持上传文档（PDF/Word）和图片 |

### 🔧 内置工具
| 工具 | 权限级别 | 说明 |
|------|---------|------|
| `web_search` | 🟢 自动 | 联网搜索（Tavily API），支持多关键词交叉验证 |
| `read_file` | 🟢 自动 | 读取本地文件内容 |
| `list_directory` | 🟢 自动 | 列出目录下的文件和子目录 |
| `write_file` | 🟡 需确认 | 写入/创建文件（自动快照备份） |

### 🌐 多模型支持
开箱即用支持主流 LLM 提供商：
- Anthropic (Claude) / Google (Gemini) / OpenAI / DeepSeek
- 阿里百炼 DashScope（GLM、Kimi、MiniMax 等）
- 字节豆包 Doubao / 小米 MiLM

## 🏗️ 架构

```
┌─────────────────┐     SSE 事件流     ┌──────────────────────────────┐
│  React + Vite   │ ◄═══════════════► │  FastAPI (server.py)         │
│  前端 Web UI     │                   │  ├── /api/chat/agent  (Agent)│
└─────────────────┘                   │  ├── /api/chat/stream (Chat) │
                                      │  └── /api/sessions/* (会话)  │
                                      └─────────┬────────────────────┘
                                                │
                              ┌─────────────────┼─────────────────┐
                              │           Agent Loop              │
                              │  ┌───────────────────────────┐    │
                              │  │ while turn < 25:          │    │
                              │  │   ① compact check         │    │
                              │  │   ② build system prompt   │    │
                              │  │   ③ LLM call (with tools) │    │
                              │  │   ④ parse response        │    │
                              │  │   ⑤ tool_use → Pipeline   │    │
                              │  │   ⑥ append result → next  │    │
                              │  └───────────────────────────┘    │
                              │                                   │
                              │  Tool Pipeline (6 阶段):          │
                              │  render → permission → preHook   │
                              │  → checkpoint → execute → postHook│
                              └───────────────────────────────────┘
```

## 📁 项目结构

```
MultiAgent/
├── server.py              # FastAPI 服务入口
├── config.yaml            # 系统配置（Provider/模型/参数）
├── start.sh               # 一键启动脚本
├── requirements.txt       # Python 依赖
│
├── agent/                 # Agent Loop 核心
│   ├── loop.py            # 自主循环引擎（25 轮上限）
│   ├── tool_pipeline.py   # 6 阶段工具执行管线
│   ├── state.py           # AgentState 可序列化状态
│   └── instructions/      # 可切换的系统提示词模板
│       ├── default.md     # 通用助手
│       └── analyst.md     # 数据分析师
│
├── tools/                 # 工具层（OpenAI Function Calling 协议）
│   ├── base.py            # BaseTool 基类
│   ├── registry.py        # ToolRegistry 统一注册中心
│   ├── web_search.py      # 联网搜索工具
│   └── file_ops.py        # 文件操作工具集
│
├── core/                  # 基础设施
│   ├── llm_client.py      # 统一 LLM 适配器（多 Provider）
│   ├── config.py          # 配置管理（热重载）
│   └── logger.py          # 结构化日志（彩色控制台 + 按日期文件）
│
├── services/              # 业务服务
│   ├── sessions.py        # 会话持久化（JSON 文件存储）
│   ├── chat.py            # 流式聊天服务
│   ├── auth.py            # 用户认证（JWT）
│   └── providers/         # LLM Provider 适配器
│
├── frontend/              # React + Vite 前端
│   └── src/
│       ├── components/    # UI 组件
│       ├── stores/        # Zustand 状态管理
│       └── utils/         # API 工具函数
│
├── logs/                  # 日志（按日期命名，如 2026-03-30.log）
├── sessions/              # 会话数据持久化目录
└── outputs/               # Agent 输出文件
```

## 🚀 快速开始

### 1. 环境准备

```bash
# 创建 Conda 环境
conda create -n multiagent python=3.11 -y
conda activate multiagent

# 安装 Python 依赖
pip install -r requirements.txt

# 安装前端依赖
cd frontend && npm install && cd ..
```

### 2. 配置 API Key

```bash
# 复制环境变量模板
cp .env.example .env
```

编辑 `.env` 文件，填入你的 API Key：
```env
DASHSCOPE_API_KEY=sk-xxx        # 阿里百炼（推荐，一个 Key 可用多个模型）
TAVILY_API_KEY=tvly-xxx          # Tavily 搜索（Agent 联网搜索需要）
# 可选
ANTHROPIC_API_KEY=sk-xxx
DEEPSEEK_API_KEY=sk-xxx
DOUBAO_API_KEY=xxx
```

### 3. 一键启动

```bash
chmod +x start.sh

./start.sh start     # 启动前后端
./start.sh status    # 查看服务状态
./start.sh restart   # 重启
./start.sh stop      # 停止
```

启动成功后：
- 🌐 前端界面：`http://localhost:3000`
- 📡 后端 API：`http://localhost:9000/docs`

### 4. 用户管理

首次使用需创建用户：
```bash
conda activate multiagent
python manage_users.py add <username> <password>
```

## ⚙️ 配置说明

### `config.yaml`

```yaml
providers:
  dashscope:                       # Provider 名称
    base_url: https://...          # API 端点
    models: [glm-5, kimi-k2.5]    # 可用模型列表

role_models:                       # 各角色使用的模型
  orchestrator:                    # Agent Loop 使用
    provider: dashscope
    model: glm-5

agent:
  instructions: default            # 系统提示词模板（对应 agent/instructions/*.md）

default_params:                    # 默认生成参数
  max_tokens: 100000
  temperature: 1.0
```

## 🔌 添加新工具

只需 3 步即可扩展工具：

```python
# tools/my_tool.py
from tools.base import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "描述工具功能"
    permission = "auto"  # auto | confirm
    
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "查询内容"}
        },
        "required": ["query"]
    }
    
    async def execute(self, **kwargs) -> str:
        # 实现工具逻辑
        return "结果"
```

然后在 `server.py` 中注册：
```python
from tools.my_tool import MyTool
new_tool_registry.register(MyTool())
```

## 📋 技术栈

| 层 | 技术 |
|---|------|
| 前端 | React 19 + Vite + Zustand + Vanilla CSS |
| 后端 | Python 3.11 + FastAPI + SSE |
| LLM 协议 | OpenAI Chat Completions (Function Calling) |
| 搜索 | Tavily API |
| 认证 | JWT (PyJWT) |
| 数据 | JSON 文件持久化 |

## 📄 License

MIT
