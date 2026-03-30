"""
Multi-Agent Workbench — FastAPI Web Server
直接对话 + Agent Loop 两种模式
"""
import json
import asyncio
import os
import sys
import logging

from typing import Optional, List
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import Config
from core.llm_client import LLMClient
from core.logger import logger

# 新 Agent 架构
from tools.base import BaseTool
from tools.registry import ToolRegistry as NewToolRegistry
from tools.web_search import WebSearchTool
from tools.file_ops import ReadFileTool, WriteFileTool, ListDirectoryTool
from agent.loop import AgentLoop
from agent.tool_pipeline import ToolPipeline
from agent.state import AgentState

# 服务模块
from services.provider_config import load_config as load_provider_config, save_config as save_provider_config
from services.sessions import (
    list_sessions, create_session, get_session,
    update_session, delete_session, clear_messages,
    pop_last_messages, append_message, save_workflow, get_workflow,
    archive_current_workflow, update_workflow_step,
    save_agent_activity, get_agent_activity
)
from services.chat import stream_chat_response
from services.tokens import count_messages_tokens
from services.files import process_image, process_document
from services.models import (
    SessionCreate, SessionUpdate, ChatRequest as DirectChatRequest,
    TokenCountRequest
)
from services.auth import authenticate, create_token, verify_token, init_default_users

# ═══════════════════════════════════════
# Logging
# ═══════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ═══════════════════════════════════════
# 全局初始化
# ═══════════════════════════════════════

config = Config()
logger.set_level(config.log_level)
llm_client = LLMClient(config)
project_root = os.path.dirname(os.path.abspath(__file__))

# ── 新 Tool 注册 ──
new_tool_registry = NewToolRegistry()

# 初始化 Tavily（如果可用）
try:
    from tools.tavily_search.client import TavilySearchTool
    tavily_client = TavilySearchTool(config)
    new_tool_registry.register(WebSearchTool(tavily_client))
    logger.info("✅ WebSearchTool 注册成功")
except Exception as e:
    logger.warning(f"⚠️ WebSearchTool 注册失败（Tavily 不可用）: {e}")

# 文件操作工具
new_tool_registry.register(ReadFileTool(project_root))
new_tool_registry.register(WriteFileTool(project_root))
new_tool_registry.register(ListDirectoryTool(project_root))

logger.info(f"Tool Registry: {new_tool_registry.list_tools()}")

# ── Tool Pipeline ──
tool_pipeline = ToolPipeline(new_tool_registry, project_root)

# ── 加载 Instructions ──
agent_config = config.raw_config.get("agent", {})
instructions_name = agent_config.get("instructions", "default")
instructions_path = os.path.join(project_root, "agent", "instructions", f"{instructions_name}.md")
try:
    with open(instructions_path, "r", encoding="utf-8") as f:
        agent_instructions = f.read()
    logger.info(f"Agent Instructions 加载: {instructions_name}")
except FileNotFoundError:
    agent_instructions = "你是一个多功能 AI 助手，可以通过工具帮助用户完成各种任务。"
    logger.warning(f"Instructions 文件不存在: {instructions_path}，使用默认")

# ── Agent Loop（全局实例映射，按 session 隔离）──
agent_loops: dict[str, AgentLoop] = {}  # session_id -> AgentLoop


def get_or_create_agent_loop(session_id: str) -> AgentLoop:
    """获取或创建 session 级别的 AgentLoop"""
    if session_id not in agent_loops:
        context_limit = agent_config.get("context_limit", 128000)
        agent_loops[session_id] = AgentLoop(
            llm_client=llm_client,
            tool_registry=new_tool_registry,
            tool_pipeline=tool_pipeline,
            instructions=agent_instructions,
            context_limit=context_limit,
        )
    return agent_loops[session_id]


logger.info("Web Server 初始化完成（新 Agent Loop 架构）")

# ═══════════════════════════════════════
# FastAPI App
# ═══════════════════════════════════════

# 初始化默认用户
init_default_users()

app = FastAPI(title="Multi-Agent Workbench API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════
# Auth 中间件
# ═══════════════════════════════════════

class AuthMiddleware(BaseHTTPMiddleware):
    """JWT authentication for all /api/* except /api/auth/*."""
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # 不拦截: 非 API 路由、auth 路由、OPTIONS 预检
        if not path.startswith("/api") or path.startswith("/api/auth") or request.method == "OPTIONS":
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse({"detail": "未登录"}, status_code=401)

        token = auth_header[7:]
        payload = verify_token(token)
        if not payload:
            return JSONResponse({"detail": "登录已过期，请重新登录"}, status_code=401)

        # 注入用户信息到 request.state
        request.state.user_id = payload["user_id"]
        request.state.username = payload["username"]
        request.state.display_name = payload.get("display_name", payload["username"])
        return await call_next(request)


app.add_middleware(AuthMiddleware)


# ═══════════════════════════════════════
# Pydantic 模型
# ═══════════════════════════════════════

from pydantic import BaseModel


class AgentChatRequest(BaseModel):
    message: str
    session_id: str = ""
    files: Optional[List[dict]] = None


class AgentInjectRequest(BaseModel):
    """用户在 Agent 执行中注入反馈"""
    message: str
    session_id: str = ""


class AgentConfirmRequest(BaseModel):
    """用户确认/拒绝破坏性工具调用"""
    approved: bool = True
    session_id: str = ""


# Legacy: 保留旧的 Pydantic 模型以防前端还在用
class ConfirmRequest(BaseModel):
    action: str = "confirm"
    modification: str = ""
    session_id: str = ""
    step_models: dict = {}


class AnswerRequest(BaseModel):
    answer: str
    session_id: str = ""


class ConfigUpdate(BaseModel):
    config: dict


# ═══════════════════════════════════════
# Auth 端点
# ═══════════════════════════════════════

class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginRequest):
    user = authenticate(body.username, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_token(user)
    return {
        "token": token,
        "user": user,
    }


@app.get("/api/auth/me")
def get_me(request: Request):
    return {
        "user_id": request.state.user_id,
        "username": request.state.username,
        "display_name": request.state.display_name,
    }


# ═══════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════

def get_user_id(request: Request) -> str:
    return getattr(request.state, "user_id", "default")


def sse_event(event_type: str, data: dict) -> str:
    payload = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
    return f"data: {payload}\n\n"


# ═══════════════════════════════════════
# 系统状态
# ═══════════════════════════════════════

@app.get("/api/status")
def get_status():
    return {
        "providers": {
            name: {"base_url": info["base_url"], "models": info["models"]}
            for name, info in config.list_providers().items()
        },
        "role_models": config.list_role_models(),
        "tools": new_tool_registry.list_tools(),
        "agents": [],  # Legacy: 旧多 Agent 已被 Agent Loop 替代
        "state": "idle",
    }


# ═══════════════════════════════════════
# 会话管理
# ═══════════════════════════════════════

@app.get("/api/sessions")
def get_sessions(request: Request):
    return list_sessions(user_id=get_user_id(request))


@app.post("/api/sessions")
def post_session(body: SessionCreate, request: Request):
    return create_session(name=body.name, system_prompt=body.system_prompt or "", params=body.params, user_id=get_user_id(request))


@app.get("/api/sessions/{session_id}")
def get_session_detail(session_id: str, request: Request):
    s = get_session(session_id, user_id=get_user_id(request))
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return s


@app.patch("/api/sessions/{session_id}")
def patch_session(session_id: str, body: SessionUpdate, request: Request):
    s = update_session(session_id, name=body.name, system_prompt=body.system_prompt,
                        params=body.params, mode=body.mode, user_id=get_user_id(request))
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return s


@app.delete("/api/sessions/{session_id}")
def del_session(session_id: str, request: Request):
    if not delete_session(session_id, user_id=get_user_id(request)):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@app.delete("/api/sessions/{session_id}/messages")
def del_messages(session_id: str, request: Request):
    if not clear_messages(session_id, user_id=get_user_id(request)):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@app.delete("/api/sessions/{session_id}/messages/last")
def del_last_messages(session_id: str, request: Request, count: int = 2):
    last_user = pop_last_messages(session_id, count, user_id=get_user_id(request))
    if last_user is None:
        raise HTTPException(status_code=404, detail="Session not found or no messages")
    return {"ok": True, "last_user_message": last_user}


# ═══════════════════════════════════════
# Workflow 持久化
# ═══════════════════════════════════════

@app.get("/api/sessions/{session_id}/workflow")
def get_session_workflow(session_id: str, request: Request):
    return get_workflow(session_id, user_id=get_user_id(request))


@app.get("/api/sessions/{session_id}/agent-activity")
def get_session_agent_activity(session_id: str, request: Request):
    """获取 session 的 Agent Loop 活动历史（工具调用记录）"""
    return get_agent_activity(session_id, user_id=get_user_id(request))


# ═══════════════════════════════════════
# 直接对话（非 Agent 模式 — ChatBot 流式）
# ═══════════════════════════════════════

@app.post("/api/chat/stream")
async def chat_stream(body: DirectChatRequest, request: Request):
    """直接对话 SSE 流（和 ChatBot 一样）"""
    cfg = load_provider_config()
    default_params = cfg.get("default_params", {})
    params = body.params

    logger.info(f"直接对话: session={body.session_id}, provider={body.provider}, model={body.model}")
    logger.debug(f"├─ message: {body.message[:100]}...")

    return StreamingResponse(
        stream_chat_response(
            session_id=body.session_id,
            user_id=get_user_id(request),
            user_message=body.message,
            files=body.files,
            provider_name=body.provider,
            model=body.model,
            system_prompt=body.system_prompt,
            max_tokens=params.max_tokens if params else default_params.get("max_tokens", 8096),
            temperature=params.temperature if params else default_params.get("temperature", 1.0),
            top_p=params.top_p if params else default_params.get("top_p", 1.0),
            frequency_penalty=params.frequency_penalty if params else default_params.get("frequency_penalty", 0.0),
            context_strategy=body.context_strategy or cfg.get("context_strategy", "rounds"),
            context_rounds=body.context_rounds or cfg.get("context_rounds", 10),
            context_token_threshold=body.context_token_threshold or cfg.get("context_token_threshold", 8000),
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ═══════════════════════════════════════
# Agent 对话（新 Agent Loop 架构）
# ═══════════════════════════════════════

@app.post("/api/chat/agent")
async def agent_chat(body: AgentChatRequest, request: Request):
    """Agent 模式 — 通过 Agent Loop 执行任务"""
    logger.info(f"Agent Loop: session={body.session_id}, message={body.message[:100]}")
    user_id = get_user_id(request)

    # 持久化用户消息到 session & 自动设置 mode
    is_first_agent_msg = False
    if body.session_id:
        append_message(body.session_id, "user", body.message, user_id=user_id)
        session_data = get_session(body.session_id, user_id=user_id)
        if session_data:
            is_first_agent_msg = len([m for m in session_data.get("messages", []) if m["role"] == "user"]) <= 1
            if session_data.get("mode") != "agent":
                update_session(body.session_id, user_id=user_id, mode="agent")

    # 拼接文件内容
    agent_message = body.message
    if body.files:
        file_parts = []
        for f in body.files:
            if f.get("type") == "image":
                file_parts.append(f"[附件图片: {f.get('filename', '图片')}]")
            elif f.get("type") == "document":
                file_parts.append(f"[附件: {f.get('filename', '文档')}]\n{f.get('text', '')}")
        if file_parts:
            agent_message = body.message + "\n\n" + "\n\n".join(file_parts)

    # 获取或创建 Agent Loop
    sid = body.session_id or "default"
    loop = get_or_create_agent_loop(sid)

    # 恢复历史（如果 loop 新建）
    if not loop.state or not loop.state.messages:
        if body.session_id:
            try:
                session = get_session(body.session_id, user_id=user_id)
                if session:
                    history_msgs = session.get("messages", [])
                    state = AgentState(session_id=sid)
                    for m in history_msgs[:-1]:
                        if m["role"] in ("user", "assistant"):
                            state.messages.append({"role": m["role"], "content": m["content"]})
                    loop.state = state
            except Exception as e:
                logger.warning(f"加载 session 历史失败: {e}")

    async def event_generator():
        collected_tool_calls = []  # 收集本次运行的所有工具调用

        try:
            async for event in loop.run(agent_message, state=loop.state):
                yield sse_event(event["type"], event.get("data", {}))

                etype = event["type"]
                edata = event.get("data", {})

                # 收集工具调用记录
                if etype == "tool_call":
                    collected_tool_calls.append({
                        "id": edata.get("id"),
                        "name": edata.get("name"),
                        "arguments": edata.get("arguments"),
                        "status": "calling",
                        "turn": edata.get("turn"),
                    })
                elif etype == "tool_result":
                    for tc in collected_tool_calls:
                        if tc["id"] == edata.get("id"):
                            tc["status"] = "done"
                            tc["result"] = edata.get("result", "")[:2000]
                            tc["elapsed"] = edata.get("elapsed")

                if body.session_id:
                    if etype == "text":
                        content = edata.get("content", "")
                        if content:
                            append_message(body.session_id, "assistant", content, user_id=user_id)
                    elif etype == "done":
                        save_workflow(body.session_id, {
                            "status": "done",
                            "turns": edata.get("turns", 0),
                            "stats": edata.get("stats", {}),
                        }, user_id=user_id)
                        # 持久化 Agent 活动记录
                        if collected_tool_calls:
                            save_agent_activity(body.session_id, {
                                "tool_calls": collected_tool_calls,
                                "turns": edata.get("turns", 0),
                                "elapsed": edata.get("elapsed", 0),
                                "total_tokens": loop.state.total_tokens if loop.state else 0,
                                "total_tool_calls": len(collected_tool_calls),
                            }, user_id=user_id)

                await asyncio.sleep(0)

            # Agent 模式自动生成标题
            if is_first_agent_msg and body.session_id:
                first_reply = ""
                if loop.state and loop.state.messages:
                    for m in loop.state.messages:
                        if m.get("role") == "assistant" and m.get("content"):
                            first_reply = m["content"]
                            break
                from services.chat import generate_title
                asyncio.create_task(generate_title(body.session_id, body.message, first_reply, user_id=user_id))

        except Exception as e:
            logger.error(f"Agent Loop error: {e}")
            yield sse_event("error", {"message": str(e)})
        yield sse_event("stream_end", {})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/agent/inject")
async def agent_inject(body: AgentInjectRequest, request: Request):
    """用户在 Agent 执行过程中注入反馈"""
    user_id = get_user_id(request)
    sid = body.session_id or "default"

    if sid in agent_loops:
        agent_loops[sid].interrupt(body.message)
        if body.session_id:
            append_message(body.session_id, "user", body.message, user_id=user_id)
        return {"ok": True, "message": "反馈已注入"}
    return {"ok": False, "message": "没有活跃的 Agent Loop"}


@app.post("/api/agent/confirm")
async def agent_confirm_tool(body: AgentConfirmRequest, request: Request):
    """用户确认或拒绝破坏性工具调用"""
    sid = body.session_id or "default"

    if sid in agent_loops:
        pipeline = agent_loops[sid].pipeline
        pipeline.grant_permission(body.approved)
        return {"ok": True, "approved": body.approved}
    return {"ok": False, "message": "没有活跃的 Agent Loop"}


@app.post("/api/agent/cancel")
async def agent_cancel(request: Request):
    """取消当前 Agent Loop"""
    cancelled = []
    for sid, loop in agent_loops.items():
        loop.cancel()
        cancelled.append(sid)
    return {"ok": True, "cancelled": cancelled}


# ═══════════════════════════════════════
# Provider 配置管理
# ═══════════════════════════════════════

@app.get("/api/config")
def get_config():
    return load_provider_config()


@app.put("/api/config")
def put_config(body: ConfigUpdate):
    save_provider_config(body.config)
    return {"ok": True}


# ═══════════════════════════════════════
# Agent 编排配置
# ═══════════════════════════════════════

import yaml

@app.get("/api/agent/config")
def get_agent_config():
    """返回 Agent 配置"""
    ag_conf = config.raw_config.get("agent", {})
    return {
        "role_models": config.list_role_models(),
        "instructions": ag_conf.get("instructions", "default"),
        "available_instructions": ag_conf.get("available_instructions", ["default"]),
        "context_limit": ag_conf.get("context_limit", 128000),
        "max_turns": ag_conf.get("max_turns", 25),
        "tools": new_tool_registry.list_tools(),
        "available_providers": {
            name: {"base_url": info["base_url"], "models": info["models"]}
            for name, info in config.list_providers().items()
        },
    }


class AgentConfigUpdate(BaseModel):
    role_models: Optional[dict] = None
    instructions: Optional[str] = None
    context_limit: Optional[int] = None


@app.put("/api/agent/config")
def put_agent_config(body: AgentConfigUpdate):
    """更新 Agent 配置"""
    global agent_instructions

    config_path = os.path.join(project_root, "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if body.role_models is not None:
        raw["role_models"] = body.role_models

    if body.instructions is not None:
        if "agent" not in raw:
            raw["agent"] = {}
        raw["agent"]["instructions"] = body.instructions
        new_path = os.path.join(project_root, "agent", "instructions", f"{body.instructions}.md")
        try:
            with open(new_path, "r", encoding="utf-8") as f:
                agent_instructions = f.read()
            for loop in agent_loops.values():
                loop.instructions = agent_instructions
            logger.info(f"Instructions 切换为: {body.instructions}")
        except FileNotFoundError:
            return {"ok": False, "error": f"Instructions 文件不存在: {body.instructions}"}

    if body.context_limit is not None:
        if "agent" not in raw:
            raw["agent"] = {}
        raw["agent"]["context_limit"] = body.context_limit

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(raw, f, allow_unicode=True, default_flow_style=False)
    config.reload()

    return {
        "ok": True,
        "role_models": config.list_role_models(),
        "instructions": raw.get("agent", {}).get("instructions", "default"),
    }


# ═══════════════════════════════════════
# Token 计数
# ═══════════════════════════════════════

@app.post("/api/tokens/count")
def count_tokens(body: TokenCountRequest):
    messages = [{"role": m.role, "content": m.content} for m in body.messages]
    count = count_messages_tokens(messages)
    return {"token_count": count}


# ═══════════════════════════════════════
# 文件上传
# ═══════════════════════════════════════

@app.post("/api/files/upload")
async def upload_file(file: UploadFile = File(...)):
    file_bytes = await file.read()
    mime_type = file.content_type or "application/octet-stream"
    filename = file.filename or "upload"

    image_mime_types = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"]

    if mime_type in image_mime_types or any(filename.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"]):
        result = process_image(file_bytes, mime_type)
    else:
        result = process_document(file_bytes, filename, mime_type)

    result["filename"] = filename
    return result


# ═══════════════════════════════════════
# 对话历史
# ═══════════════════════════════════════

@app.get("/api/history")
def get_history():
    return {"history": []}


# ═══════════════════════════════════════
# 启动
# ═══════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000, reload=False)

