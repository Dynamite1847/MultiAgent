

# 产品经理多Agent工作台 — 完整产品方案（多Agent架构版）

## 一、产品定位

**用户用自然语言说清楚"要什么"，AI自主决定"怎么做"，主要服务产品经理，撰写PRD，进行竟品调研，甚至是先进行竟品调研再写prd。**

主Agent理解意图、自动规划工作步骤 → 用户确认计划 → 子Agent分工执行 → 主Agent汇总交付。不区分场景，不硬编码流程，一切由AI实时编排。**插件化架构，新增Agent/Skill即插即用。**

---

## 二、设计原则

| 原则 | 说明 |
|------|------|
| **AI编排，人类决策** | AI规划工作流，关键节点用户确认和干预 |
| **能力原子化** | 子Agent按"能力"划分而非"场景"，Orchestrator自由组合 |
| **插件化扩展** | Agent/Skill通过manifest自描述，注册中心自动发现，无需修改核心代码 |
| **过程透明** | 用户看得到计划、中间结果、AI的判断依据、完整执行日志，不是黑箱 |
| **原生实现** | 不依赖Agent框架，手写编排逻辑，理解底层原理 |

---

## 三、系统架构

### 3.1 分层架构

```
┌──────────────────────────────────────────┐
│          用户交互层（CLI → API → Web）     │
├──────────────────────────────────────────┤
│            Orchestrator（主Agent）         │
│意图理解 → 需求澄清 → 计划生成            │
│→ 执行调度 → 动态调整 → 结果汇总          │
├──────────────────────────────────────────┤
│           Agent注册中心（Registry）        │
│  自动发现 → 能力注册 → 动态Prompt生成    │
├────────┬────────┬─────────┬──────────────┤
│ Search │Analysis│ Writing │  Interview   │
│ Agent  │ Agent  │ Agent   │  Agent       │
│ (插件) │ (插件) │ (插件)  │  (插件)      │
├────────┴────────┴─────────┴──────────────┤
│           工具注册中心（Tool Registry）    │
├────────┬────────┬─────────┬──────────────┤
│ Tavily │ GitHub │  File   │   ...        │
│ Search │  API   │ Writer  │              │
└────────┴────────┴─────────┴──────────────┘
```

### 3.2 插件化机制

#### Agent插件标准

每个Agent是一个独立目录，包含：

```
agents/web_search/
├── manifest.yaml       # 自描述文件（身份、能力、使用场景）
├── agent.py            # 实现（继承BaseAgent）
└── prompts.md          # System Prompt
```

**manifest.yaml 结构：**

```yaml
name: web_search                    # 唯一标识
display_name: "网络搜索"
description: "搜索互联网获取实时信息，适用于调研、信息收集、事实核查"
version: "1.0"

# Orchestrator靠这段话决定什么时候用这个Agent
when_to_use: |
  - 用户需要了解某个产品、公司、技术的最新信息
  - 需要收集行业数据、竞品信息、用户评价
  - 需要验证某个事实或获取实时数据

# 输入规范
input_schema:
  queries:
    type: list[str]
    description: "搜索查询列表，支持多条并行搜索"
    required: true
  search_depth:
    type: string
    enum: [basic, advanced]
    default: basic
    required: false

# 输出规范
output_schema:
  results:
    type: string
    description: "结构化搜索结果，Markdown格式"

# 依赖的工具
tools_required:
  - tavily_search

# 入口类
entry_point: "agents.web_search.agent:WebSearchAgent"
```

#### Tool插件标准

```
tools/tavily_search/
├── manifest.yaml       # 工具自描述
└── client.py           # 工具实现
```

**manifest.yaml 结构：**

```yaml
name: tavily_search
type: tool
display_name: "Tavily搜索"
description: "互联网实时搜索API"
version: "1.0"

# 需要的配置项
config_required:
  - TAVILY_API_KEY

# 入口
entry_point: "tools.tavily_search.client:TavilySearchTool"
```

#### 注册中心工作流程

```
系统启动↓
Agent Registry 扫描 agents/ 目录
  ├─ 读取所有 manifest.yaml
  ├─ 验证schema完整性
  ├─ 检查依赖的tools是否可用
  ├─ 动态加载Agent类
  └─ 注册为Orchestrator的可用工具
     ↓
Tool Registry 扫描 tools/ 目录
  ├─ 读取所有 manifest.yaml
  ├─ 检查配置项是否齐全
  ├─ 动态加载Tool类
  └─ 注册到工具池
     ↓
Prompt Builder 根据注册的Agent动态生成Orchestrator的System Prompt
     ↓
Orchestrator 启动，拥有所有已注册Agent的调用能力
```

---

### 3.3 Orchestrator（主Agent）

**角色：全局指挥官。** 不亲自干活，只负责理解、规划、调度、评估、汇总。

**核心能力：**

| 能力 | 描述 | 触发条件 |
|------|------|---------|
| 意图理解 | 解析自然语言，识别任务本质 | 收到用户输入 |
| 需求澄清 | 多轮追问，消除歧义 | 判断需求不够明确 |
| 计划生成 | 输出结构化执行计划 | 需求明确后 |
| 执行调度 | 按依赖关系逐步调用子Agent | 用户确认计划后 |
| 动态调整 | 根据中间结果修改后续计划 | 步骤结果不符合预期 |
| 结果汇总 | 整合全部输出，生成最终交付物 | 所有步骤完成 |

**状态机：**

```
收到需求 → 理解意图
              ↓
        [需求清晰？]── 否──→ 多轮澄清对话 ─┐
              │ 是                        │
              ↓                           │
         生成执行计划 ←─────────────────────┘
              ↓
      ⏸️ 展示计划，等待用户确认
              ↓ 确认
         逐步执行
              ↓ 每步完成后
        [评估结果质量]
         ├─ 符合预期 → 继续下一步
         ├─ 信息不足 → 自动补充步骤
         └─ 方向偏移 → 修改计划 + 通知用户
              ↓ 全部完成
         汇总最终结果
              ↓
      ⏸️ 展示结果，等待用户确认
              ↓
         完成交付
```

**Orchestrator的Prompt是动态生成的：**

```
【固定部分】
你是PM多Agent工作台的主控Agent。
你的职责是理解需求、规划步骤、调度执行、汇总结果。
你自己不做具体工作，只分配给子Agent。

【动态部分 - 由Prompt Builder根据Registry自动生成】
当前可用的子Agent（共4个）：

1. [web_search] 网络搜索
   适用场景：
   - 用户需要了解某个产品、公司、技术的最新信息
   - 需要收集行业数据、竞品信息、用户评价
   输入：queries(list[str]), search_depth(optional)

2. [analysis] 分析整合
   适用场景：
   - 需要对信息进行对比、归纳、洞察
   - 需要提炼关键结论
   输入：content(str), requirement(str)

3. [writing] 文档撰写
   适用场景：
   - 需要生成完整文档（PRD/报告/总结）
   输入：content(str), doc_requirement(str)

4. [interview] 用户访谈
   适用场景：
   - 需要深入了解用户需求细节
   - 需要多轮对话确认关键信息
   输入：topics(list[str])

【固定部分】
规则：
- 计划必须输出为指定JSON格式
- 关键步骤标记pause_after=true
- 评估结果时如发现信息不足，主动增加步骤
```

**未来新增Agent后，动态部分自动更新，Orchestrator无需改代码。**

---

### 3.4 MVP阶段的Agent插件

#### ① WebSearchAgent（网络搜索）

| 项目 | 内容 |
|------|------|
| **职责** | 根据查询搜索互联网，返回结构化信息 |
| **工具** | Tavily Search API |
| **输入** | queries: list[str], search_depth: basic/advanced |
| **输出** | 结构化搜索结果：标题、摘要、URL、关键信息提取 |
| **自主性** | 可根据首轮结果自主生成follow-up查询深挖 |

#### ② AnalysisAgent（分析整合）

| 项目 | 内容 |
|------|------|
| **职责** | 对信息进行深度分析、对比、归纳 |
| **工具** | 无外部工具，纯LLM推理 |
| **输入** | content: str, requirement: str |
| **输出** | 分析结论（自动选择框架：对比分析/SWOT/趋势归纳/要点提炼等） |
| **自主性** | 自动判断最合适的分析方法 |

#### ③ WritingAgent（文档撰写）

| 项目 | 内容 |
|------|------|
| **职责** | 根据素材和要求生成完整文档 |
| **工具** | 无外部工具，纯LLM生成 |
| **输入** | content: str, doc_requirement: str |
| **输出** | 完整文档（Markdown格式） |
| **自主性** | 自动选择文档结构，不限文档类型 |

#### ④ InterviewAgent（用户访谈）⚠️ 特殊Agent
这个agent的目的是，项目有很多细节，这个agent应当是一个共创人，通过向产品提问，完善设想而不是凭空编造。

| 项目 | 内容 |
|------|------|
| **职责** | 与用户进行结构化多轮对话，提取关键信息 |
| **工具** | 无外部工具，直接与用户对话 |
| **输入** | topics: list[str] |
| **输出** | 结构化的访谈摘要 |
| **特殊性** | 唯一需要暂停工作流让用户参与的Agent |

---

## 四、核心流程设计

### 4.1 执行计划格式

Orchestrator生成的计划是一个结构化JSON：

```json
{
  "goal": "调研Cursor这款AI编程产品",
  "steps": [
    {
      "step_id": 1,
      "description": "搜索Cursor的基本信息、核心功能、最新动态",
      "agent": "web_search",
      "input": {
        "queries": [
          "Cursor AI代码编辑器 功能特性 2024",
          "Cursor最新版本更新"
        ],
        "search_depth": "basic"
      },
      "depends_on": [],
      "pause_after": false
    },
    {
      "step_id": 2,
      "description": "搜索Cursor的竞品对比和用户评价",
      "agent": "web_search",
      "input": {
        "queries": [
          "Cursor vs GitHub Copilot 对比",
          "Cursor 用户评价 优缺点"
        ]
      },
      "depends_on": [],
      "pause_after": false
    },
    {
      "step_id": 3,
      "description": "分析整合搜索结果，提炼核心洞察",
      "agent": "analysis",
      "input": {
        "source_steps": [1, 2],
        "requirement": "产品定位、核心卖点、目标用户、竞争格局"
      },
      "depends_on": [1, 2],
      "pause_after": true
    },
    {
      "step_id": 4,
      "description": "撰写完整产品调研报告",
      "agent": "writing",
      "input": {
        "source_steps": [1, 2, 3],
        "requirement": "完整调研报告，包含产品概述、功能分析、竞品对比、结论建议"
      },
      "depends_on": [3],
      "pause_after": false
    }
  ]
}
```

### 4.2 上下文传递机制

```
Step 1 输出──┐
Step 2 输出──┤──→ Step 3 输入（前序步骤的结果全部拼入上下文）
             │
Step 3 输出──┤──→ Step 5 输入
Step 4 输出──┘
             │
Step 5 输出──┤──→ Step 6 输入
```

每步的输出存储在执行计划中。后续步骤执行时，Orchestrator将所有 `depends_on` 步骤的结果拼入子Agent的上下文。

### 4.3 动态调整示例

```
执行 Step 1（搜索社区团购竞品）
     ↓
Orchestrator评估结果："搜索结果主要是2022年的，信息可能过时"
     ↓
自动插入 Step 1.5：[搜索] "2024年社区团购最新动态 新入局者"
     ↓
通知用户："我发现搜索结果偏旧，已补充一轮搜索获取最新信息"
     ↓
继续执行
```

---

## 五、半自动交互机制

### 5.1 暂停点类型

| 类型 | 触发条件 | 用户可操作 |
|------|---------|-----------|
| **计划确认** | 计划生成后 | 确认 / 修改 / 取消 |
| **阶段检查** | Orchestrator标记的关键步骤完成后 | 确认继续 / 调整方向 / 追加要求 / 终止 |
| **用户参与** | InterviewAgent被调用时 | 与Agent多轮对话 |
| **计划变更** | Orchestrator动态调整计划时 | 同意 / 拒绝变更 |
| **异常处理** | 子Agent执行失败 | 重试 / 跳过 / 终止 |

### 5.2 CLI交互示意

**计划确认：**
```
══════════════════════════════════════════
🎯 任务：调研Cursor这款AI编程产品
══════════════════════════════════════════
📋 执行计划：
  Step 1  [🔍 搜索] Cursor基本信息和核心功能
  Step 2  [🔍 搜索] Cursor竞品对比和用户评价
  Step 3  [📊 分析] 整合信息，提炼核心洞察  ⏸️
  Step 4  [📝 撰写] 输出完整调研报告
══════════════════════════════════════════
⏸️ = 该步骤完成后暂停让你确认

> 确认执行(y) / 修改计划(e) / 取消(q): _
```

**执行中：**
```
▶ Step 1/4 [🔍 搜索] Cursor基本信息和核心功能...
  ✅ 完成 — 找到12条相关结果

▶ Step 2/4 [🔍 搜索] Cursor竞品对比...
  ✅ 完成 — 找到8条相关结果

▶ Step 3/4 [📊 分析] 整合信息...
  ✅ 完成

⏸️ 阶段检查 — Step 3 分析结果：
──────────────────────────────────
[展示分析结果摘要]
──────────────────────────────────
> 继续(y) / 调整方向(e) / 终止(q): _
```

---

## 六、日志系统需求

### 6.1 日志层级

| 层级 | 用途 | 示例 |
|------|------|------|
| **DEBUG** | 开发调试，记录所有内部状态变化 | "Registry加载agent: web_search" |
| **INFO** | 关键流程节点 | "Orchestrator生成执行计划" |
| **WARNING** | 非致命问题 | "Step 1搜索结果质量偏低，建议补充查询" |
| **ERROR** | 执行失败 | "Step 2调用web_search失败：API超时" |

### 6.2 日志内容要求

#### 系统启动日志

```
[2024-01-15 10:23:45] [INFO] PM Copilot 启动
[2024-01-15 10:23:45] [DEBUG] 加载配置: config.yaml
[2024-01-15 10:23:45] [INFO] Tool Registry 初始化
[2024-01-15 10:23:45] [DEBUG]   ├─ 发现工具: tavily_search
[2024-01-15 10:23:45] [DEBUG]   │  └─ 检查配置: TAVILY_API_KEY ✓
[2024-01-15 10:23:45] [DEBUG]   └─ 注册成功: tavily_search v1.0
[2024-01-15 10:23:45] [INFO] Agent Registry 初始化
[2024-01-15 10:23:46] [DEBUG]   ├─ 扫描目录: agents/
[2024-01-15 10:23:46] [DEBUG]   ├─ 发现Agent: web_search
[2024-01-15 10:23:46] [DEBUG]   │  ├─ 验证manifest: ✓
[2024-01-15 10:23:46] [DEBUG]   │  ├─ 检查依赖工具: tavily_search ✓
[2024-01-15 10:23:46] [DEBUG]   │  └─ 注册成功: web_search v1.0
[2024-01-15 10:23:46] [DEBUG]   ├─ 发现Agent: analysis
[2024-01-15 10:23:46] [DEBUG]   │  └─ 注册成功: analysis v1.0
[2024-01-15 10:23:46] [DEBUG]   ├─ 发现Agent: writing
[2024-01-15 10:23:46] [DEBUG]   │  └─ 注册成功: writing v1.0
[2024-01-15 10:23:46] [INFO] 共注册3个Agent，1个工具
[2024-01-15 10:23:46] [INFO] Prompt Builder 生成Orchestrator System Prompt
[2024-01-15 10:23:46] [DEBUG]   └─ Prompt长度: 1247 tokens
[2024-01-15 10:23:46] [INFO] Orchestrator 初始化完成
[2024-01-15 10:23:46] [INFO] 系统就绪，等待用户输入
```

#### 任务执行日志

```
[2024-01-15 10:25:12] [INFO] 收到用户输入: "帮我调研一下Cursor这款产品"
[2024-01-15 10:25:12] [INFO] 创建任务: task_a3f9b2c1
[2024-01-15 10:25:12] [DEBUG] Orchestrator 开始理解意图
[2024-01-15 10:25:12] [DEBUG]   └─ LLM调用: gpt-4o (temperature=0.7)
[2024-01-15 10:25:14] [DEBUG]   └─ 响应: 需求明确，无需澄清
[2024-01-15 10:25:14] [INFO] Orchestrator 生成执行计划
[2024-01-15 10:25:14] [DEBUG]   └─ LLM调用: gpt-4o (temperature=0.3)
[2024-01-15 10:25:16] [DEBUG]   └─ 计划包含4个步骤
[2024-01-15 10:25:16] [INFO] 展示计划，等待用户确认
[2024-01-15 10:25:16] [DEBUG] 计划详情:
  Step 1: [web_search] 搜索Cursor基本信息
  Step 2: [web_search] 搜索Cursor竞品对比
  Step 3: [analysis] 分析整合 (pause_after=true)
  Step 4: [writing] 撰写报告

[2024-01-15 10:25:23] [INFO] 用户确认执行
[2024-01-15 10:25:23] [INFO] 开始执行 Step 1/4
[2024-01-15 10:25:23] [DEBUG]   ├─ Agent: web_search
[2024-01-15 10:25:23] [DEBUG]   ├─ 输入: {"queries": ["Cursor AI代码编辑器 功能特性 2024", "Cursor最新版本更新"]}
[2024-01-15 10:25:23] [DEBUG]   └─ 调用工具: tavily_search
[2024-01-15 10:25:24] [DEBUG]      ├─ Query 1: "Cursor AI代码编辑器 功能特性 2024"
[2024-01-15 10:25:25] [DEBUG]      │  └─ 返回7条结果
[2024-01-15 10:25:25] [DEBUG]      ├─ Query 2: "Cursor最新版本更新"
[2024-01-15 10:25:26] [DEBUG]      │  └─ 返回5条结果
[2024-01-15 10:25:26] [DEBUG]   └─ WebSearchAgent 处理结果
[2024-01-15 10:25:27] [DEBUG]      └─ LLM调用: gpt-4o (提取关键信息)
[2024-01-15 10:25:29] [INFO]   ✅ Step 1 完成 (耗时6.2s, tokens: 2341)
[2024-01-15 10:25:29] [DEBUG]   └─ 输出长度: 1523字符

[2024-01-15 10:25:29] [INFO] 开始执行 Step 2/4
[2024-01-15 10:25:29] [DEBUG]   ├─ Agent: web_search
[2024-01-15 10:25:29] [DEBUG]   └─ 输入: {"queries": ["Cursor vs GitHub Copilot 对比", "Cursor 用户评价 优缺点"]}
[2024-01-15 10:25:29] [DEBUG]   └─ 调用工具: tavily_search
[2024-01-15 10:25:31] [DEBUG]      └─ 返回8条结果
[2024-01-15 10:25:33] [INFO]   ✅ Step 2 完成 (耗时4.1s, tokens: 1892)

[2024-01-15 10:25:33] [INFO] 开始执行 Step 3/4
[2024-01-15 10:25:33] [DEBUG]   ├─ Agent: analysis
[2024-01-15 10:25:33] [DEBUG]   ├─ 依赖步骤: [1, 2]
[2024-01-15 10:25:33] [DEBUG]   ├─ 组装上下文: Step 1输出(1523字符) + Step 2输出(1347字符)
[2024-01-15 10:25:33] [DEBUG]   └─ LLM调用: gpt-4o (分析模式)
[2024-01-15 10:25:38] [INFO]   ✅ Step 3 完成 (耗时5.3s, tokens: 3124)
[2024-01-15 10:25:38] [INFO] ⏸️ 暂停点 - Step 3 完成，等待用户确认

[2024-01-15 10:26:05] [INFO] 用户确认继续
[2024-01-15 10:26:05] [INFO] 开始执行 Step 4/4
[2024-01-15 10:26:05] [DEBUG]   ├─ Agent: writing
[2024-01-15 10:26:05] [DEBUG]   ├─ 依赖步骤: [1, 2, 3]
[2024-01-15 10:26:05] [DEBUG]   ├─ 组装上下文: 总计4217字符
[2024-01-15 10:26:05] [DEBUG]   └─ LLM调用: gpt-4o (文档生成)
[2024-01-15 10:26:12] [INFO]   ✅ Step 4 完成 (耗时7.1s, tokens: 4532)

[2024-01-15 10:26:12] [INFO] 所有步骤执行完成
[2024-01-15 10:26:12] [INFO] Orchestrator 汇总结果
[2024-01-15 10:26:12] [DEBUG]   └─ LLM调用: gpt-4o (结果整合)
[2024-01-15 10:26:15] [INFO] 任务完成
[2024-01-15 10:26:15] [INFO] 总耗时: 63秒, 总tokens: 14230
```

#### 异常日志

```
[2024-01-15 10:30:45] [ERROR] Step 2 执行失败
[2024-01-15 10:30:45] [ERROR]   ├─ Agent: web_search
[2024-01-15 10:30:45] [ERROR]   ├─ 错误类型: TavilyAPIError
[2024-01-15 10:30:45] [ERROR]   ├─ 错误信息: API rate limit exceeded
[2024-01-15 10:30:45] [ERROR]   └─ 堆栈:
    File "agents/web_search/agent.py", line 45, in execute
      results = self.tavily.search(query)
    File "tools/tavily_search/client.py", line 23, in search
      raise TavilyAPIError(response.json()['error'])
[2024-01-15 10:30:45] [WARNING] Orchestrator 评估: 可重试
[2024-01-15 10:30:45] [INFO] 询问用户: 重试 / 跳过 / 终止
```

#### 动态调整日志

```
[2024-01-15 10:35:22] [INFO] Step 1 完成
[2024-01-15 10:35:22] [INFO] Orchestrator 评估结果质量
[2024-01-15 10:35:22] [DEBUG]   └─ LLM调用: gpt-4o (质量评估)
[2024-01-15 10:35:24] [WARNING] 评估结论: 搜索结果主要来自2022年，信息可能过时
[2024-01-15 10:35:24] [INFO] Orchestrator 决定调整计划
[2024-01-15 10:35:24] [DEBUG]   └─ 插入新步骤: Step 1.5 [web_search] 搜索2024最新动态
[2024-01-15 10:35:24] [INFO] 通知用户: 计划已调整，增加补充搜索步骤
[2024-01-15 10:35:24] [DEBUG] 更新后的计划:
  Step 1: [web_search] 搜索Cursor基本信息 ✅
  Step 1.5: [web_search] 搜索2024最新动