"""
Multi-Agent Workbench — FastAPI Web Server
直接对话 + Agent 编排两种模式
"""
import json
import asyncio
import os
import sys
import logging

from typing import Optional, List
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import Config
from core.llm_client import LLMClient
from core.tool_registry import ToolRegistry
from core.agent_registry import AgentRegistry
from core.internal_tools import InternalTools
from orchestrator.orchestrator import Orchestrator
from core.logger import logger

# 服务模块
from services.provider_config import load_config as load_provider_config, save_config as save_provider_config
from services.sessions import (
    list_sessions, create_session, get_session,
    update_session, delete_session, clear_messages,
    pop_last_messages, append_message, save_workflow, get_workflow,
    archive_current_workflow, update_workflow_step
)
from services.chat import stream_chat_response
from services.tokens import count_messages_tokens
from services.files import process_image, process_document
from services.models import (
    SessionCreate, SessionUpdate, ChatRequest as DirectChatRequest,
    TokenCountRequest
)

# ═══════════════════════════════════════
# Logging — 使用 MultiAgent 的 logger 风格
# ═══════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ═══════════════════════════════════════
# 全局初始化 — Agent 系统
# ═══════════════════════════════════════

config = Config()
logger.set_level(config.log_level)

tool_registry = ToolRegistry()
tool_registry.discover_and_register(config)

llm_client = LLMClient(config)

agent_registry = AgentRegistry()
agent_registry.discover_and_register(config, llm_client, tool_registry)

project_root = os.path.dirname(os.path.abspath(__file__))
internal_tools = InternalTools(
    project_root,
    tool_registry=tool_registry,
    agent_registry=agent_registry,
    config=config,
    llm_client=llm_client,
)

orchestrator = Orchestrator(config, llm_client, agent_registry, internal_tools)
orchestrator.initialize()
internal_tools.set_orchestrator(orchestrator)

logger.info("Web Server 初始化完成")

# ═══════════════════════════════════════
# FastAPI App
# ═══════════════════════════════════════

app = FastAPI(title="Multi-Agent Workbench API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════
# Pydantic 模型（Agent 模式用）
# ═══════════════════════════════════════

from pydantic import BaseModel


class AgentChatRequest(BaseModel):
    message: str
    session_id: str = ""
    files: Optional[List[dict]] = None


class ConfirmRequest(BaseModel):
    action: str = "confirm"
    modification: str = ""
    session_id: str = ""
    step_models: dict = {}  # step_id -> "provider/model"


class AnswerRequest(BaseModel):
    answer: str
    session_id: str = ""


class ConfigUpdate(BaseModel):
    config: dict


# ═══════════════════════════════════════
# SSE 工具
# ═══════════════════════════════════════

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
        "tools": tool_registry.list_tools(),
        "agents": [
            {
                "name": name,
                "display_name": agent_registry.get_manifest(name).get("display_name", name),
                "description": agent_registry.get_manifest(name).get("description", ""),
            }
            for name in agent_registry.list_agents()
        ],
        "state": orchestrator.state,
    }


# ═══════════════════════════════════════
# 会话管理
# ═══════════════════════════════════════

@app.get("/api/sessions")
def get_sessions():
    return list_sessions()


@app.post("/api/sessions")
def post_session(body: SessionCreate):
    return create_session(name=body.name, system_prompt=body.system_prompt or "", params=body.params)


@app.get("/api/sessions/{session_id}")
def get_session_detail(session_id: str):
    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return s


@app.patch("/api/sessions/{session_id}")
def patch_session(session_id: str, body: SessionUpdate):
    s = update_session(session_id, name=body.name, system_prompt=body.system_prompt,
                        params=body.params, mode=body.mode)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return s


@app.delete("/api/sessions/{session_id}")
def del_session(session_id: str):
    if not delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@app.delete("/api/sessions/{session_id}/messages")
def del_messages(session_id: str):
    if not clear_messages(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@app.delete("/api/sessions/{session_id}/messages/last")
def del_last_messages(session_id: str, count: int = 2):
    last_user = pop_last_messages(session_id, count)
    if last_user is None:
        raise HTTPException(status_code=404, detail="Session not found or no messages")
    return {"ok": True, "last_user_message": last_user}


# ═══════════════════════════════════════
# Workflow 持久化
# ═══════════════════════════════════════

@app.get("/api/sessions/{session_id}/workflow")
def get_session_workflow(session_id: str):
    return get_workflow(session_id)


# ═══════════════════════════════════════
# 直接对话（非 Agent 模式 — ChatBot 流式）
# ═══════════════════════════════════════

@app.post("/api/chat/stream")
async def chat_stream(body: DirectChatRequest):
    """直接对话 SSE 流（和 ChatBot 一样）"""
    cfg = load_provider_config()
    default_params = cfg.get("default_params", {})
    params = body.params

    logger.info(f"直接对话: session={body.session_id}, provider={body.provider}, model={body.model}")
    logger.debug(f"├─ message: {body.message[:100]}...")

    return StreamingResponse(
        stream_chat_response(
            session_id=body.session_id,
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
# Agent 对话（多 Agent 编排）
# ═══════════════════════════════════════

@app.post("/api/chat/agent")
async def agent_chat(body: AgentChatRequest):
    """Agent 模式 SSE 流"""
    logger.info(f"Agent 对话: session={body.session_id}, message={body.message[:100]}")

    # 持久化用户消息到 session & 自动设置 mode
    is_first_agent_msg = False
    if body.session_id:
        append_message(body.session_id, "user", body.message)
        # 自动设为 agent 模式
        session_data = get_session(body.session_id)
        if session_data:
            is_first_agent_msg = len([m for m in session_data.get("messages", []) if m["role"] == "user"]) <= 1
            if session_data.get("mode") != "agent":
                update_session(body.session_id, mode="agent")

    # 拼接文件内容到消息中
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

    # 将 session 历史加载到 orchestrator 的对话上下文
    if body.session_id:
        try:
            session = get_session(body.session_id)
            if session:
                history_msgs = session.get("messages", [])
                orchestrator.conversation_history = [
                    {"role": m["role"], "content": m["content"]}
                    for m in history_msgs
                    if m["role"] in ("user", "assistant")
                ][:-1]
        except Exception as e:
            logger.warning(f"加载 session 历史失败: {e}")

    # 新任务开始前，归档现有的工作流
    if body.session_id:
        archive_current_workflow(body.session_id)

    async def event_generator():
        workflow_steps_acc = []
        try:
            async for event in orchestrator.run_stream(agent_message):
                yield sse_event(event["type"], event.get("data", {}))

                etype = event["type"]
                sid = body.session_id

                if sid:
                    # 持久化 AI 回复、汇总、澄清问题
                    if etype in ("reply", "summary"):
                        content = event.get("data", {}).get("content", "")
                        if content:
                            append_message(sid, "assistant", content)
                    elif etype == "clarify":
                        questions = event.get("data", {}).get("questions", [])
                        if questions:
                            content = "我需要了解更多信息：\n\n" + "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
                            append_message(sid, "assistant", content)

                    # 持久化工作流数据
                    elif etype == "plan":
                        save_workflow(sid, {
                            "plan": event.get("data", {}),
                            "steps": [],
                            "status": "waiting_confirm",
                        })
                    elif etype == "step_result":
                        step_data = event.get("data", {})
                        workflow_steps_acc.append(step_data)
                        update_workflow_step(sid, step_data.get("step_id"), step_data)
                        save_workflow(sid, {
                            "plan": orchestrator.plan,
                            "steps": workflow_steps_acc,
                            "status": "executing",
                        })
                    elif etype == "done" and workflow_steps_acc:
                        save_workflow(sid, {
                            "plan": orchestrator.plan,
                            "steps": workflow_steps_acc,
                            "status": "done",
                        })
                    elif etype in ("step_pause", "step_review"):
                        save_workflow(sid, {
                            "plan": orchestrator.plan,
                            "steps": workflow_steps_acc,
                            "status": "paused",
                        })

                await asyncio.sleep(0)

            # Agent 模式自动生成标题
            if is_first_agent_msg and sid:
                first_reply = ""
                for m_data in (session_data or {}).get("messages", []):
                    if m_data.get("role") == "assistant":
                        first_reply = m_data.get("content", "")
                        break
                if not first_reply:
                    first_reply = orchestrator.plan.get("goal", "") if orchestrator.plan else ""
                from services.chat import generate_title
                asyncio.create_task(generate_title(sid, body.message, first_reply))

        except Exception as e:
            logger.error(f"Agent stream error: {e}")
            yield sse_event("error", {"message": str(e)})
        yield sse_event("stream_end", {})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/task/pause")
async def pause_task():
    """暂停当前执行"""
    orchestrator.pause()
    return {"ok": True, "message": "已暂停"}


@app.post("/api/task/resume")
async def resume_task():
    """恢复执行"""
    orchestrator.resume()
    return {"ok": True, "message": "已恢复"}


class RetryRequest(BaseModel):
    step_id: str
    session_id: str = ""


@app.post("/api/task/retry")
async def retry_step(body: RetryRequest):
    """重试失败的步骤"""
    async def event_generator():
        try:
            async for event in orchestrator.retry_step(body.step_id):
                yield sse_event(event["type"], event.get("data", {}))
        except Exception as e:
            logger.error(f"Retry stream error: {e}")
            yield sse_event("error", {"message": str(e)})
        yield sse_event("stream_end", {})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/task/confirm")
async def confirm_task(body: ConfirmRequest):
    # 如果 orchestrator 没有计划但 session 有等待确认的计划，从 session 恢复
    if not orchestrator.plan and body.session_id:
        from services.sessions import get_session
        session = get_session(body.session_id)
        if session:
            wf = session.get("workflow", {})
            if wf.get("status") == "waiting_confirm" and wf.get("plan"):
                orchestrator.plan = wf["plan"]
                orchestrator.state = orchestrator.STATE_IDLE
                # 恢复对话历史
                orchestrator.conversation_history = [
                    {"role": m["role"], "content": m["content"]}
                    for m in session.get("messages", [])
                    if m["role"] in ("user", "assistant")
                ]
                logger.info(f"从 session {body.session_id} 恢复待确认计划")

    if not orchestrator.plan:
        raise HTTPException(status_code=400, detail="没有待确认的计划")

    if body.action == "cancel":
        orchestrator.state = orchestrator.STATE_IDLE
        return {"ok": True, "message": "任务已取消"}

    if body.action == "modify" and body.modification:
        old_plan = orchestrator.plan
        messages = [
            {"role": "system", "content": orchestrator.system_prompt},
            {"role": "user", "content": f"""原计划:
{json.dumps(old_plan, ensure_ascii=False, indent=2)}

用户反馈: {body.modification}

请根据用户反馈修改计划，输出新的JSON格式计划。"""},
        ]
        new_plan = llm_client.call_json(messages, role="orchestrator", temperature=0.3)
        orchestrator.plan = new_plan
        return {"ok": True, "plan": new_plan}

    sid = body.session_id

    async def event_generator():
        workflow_steps = []
        try:
            async for event in orchestrator.run_plan_stream(step_models=body.step_models):
                yield sse_event(event["type"], event.get("data", {}))
                etype = event["type"]
                if sid:
                    if etype == "summary":
                        content = event.get("data", {}).get("content", "")
                        if content:
                            append_message(sid, "assistant", content)
                    elif etype == "step_result":
                        step_data = event.get("data", {})
                        workflow_steps.append(step_data)
                        update_workflow_step(sid, step_data.get("step_id"), step_data)
                        save_workflow(sid, {
                            "plan": orchestrator.plan,
                            "steps": workflow_steps,
                            "status": "executing",
                        })
                    elif etype == "done":
                        save_workflow(sid, {
                            "plan": orchestrator.plan,
                            "steps": workflow_steps,
                            "status": "done",
                        })
                    elif etype in ("step_pause", "step_review"):
                        save_workflow(sid, {
                            "plan": orchestrator.plan,
                            "steps": workflow_steps,
                            "status": "paused",
                        })
                await asyncio.sleep(0)
        except Exception as e:
            logger.error(f"Execution error: {e}")
            yield sse_event("error", {"message": str(e)})
        yield sse_event("stream_end", {})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/task/answer")
async def answer_clarification(body: AnswerRequest):
    sid = body.session_id

    # 持久化用户回答
    if sid:
        append_message(sid, "user", body.answer)

    # ── 情况 1: 工作流执行中暂停（step_pause）→ 恢复执行 ──
    if orchestrator.is_paused():
        async def resume_generator():
            workflow_steps_acc = []
            try:
                async for event in orchestrator.run_plan_stream(resume_answer=body.answer):
                    yield sse_event(event["type"], event.get("data", {}))

                    if sid:
                        etype = event["type"]
                        if etype == "step_result":
                            step_data = event.get("data", {})
                            workflow_steps_acc.append(step_data)
                            update_workflow_step(sid, step_data.get("step_id"), step_data)
                            save_workflow(sid, {
                                "plan": orchestrator.plan,
                                "steps": workflow_steps_acc,
                                "status": "executing",
                            })
                        elif etype in ("summary",):
                            content = event.get("data", {}).get("content", "")
                            if content:
                                append_message(sid, "assistant", content)
                        elif etype == "done" and workflow_steps_acc:
                            save_workflow(sid, {
                                "plan": orchestrator.plan,
                                "steps": workflow_steps_acc,
                                "status": "done",
                            })
                        elif etype in ("step_pause", "step_review"):
                            # 暂停或审查暂停，保存当前状态
                            save_workflow(sid, {
                                "plan": orchestrator.plan,
                                "steps": workflow_steps_acc,
                                "status": "paused",
                            })
                    await asyncio.sleep(0)
            except Exception as e:
                logger.error(f"Resume stream error: {e}")
                yield sse_event("error", {"message": str(e)})
            yield sse_event("stream_end", {})

        return StreamingResponse(
            resume_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── 情况 2: 意图澄清阶段（clarify 事件后）→ 拼接答案重新开始 ──
    enriched_input = f"{orchestrator.user_request}\n\n补充信息: {body.answer}"

    # 新任务开始前归档
    if sid:
        archive_current_workflow(sid)

    async def event_generator():
        try:
            async for event in orchestrator.run_stream(enriched_input):
                yield sse_event(event["type"], event.get("data", {}))
                if sid:
                    etype = event["type"]
                    if etype in ("reply", "summary"):
                        content = event.get("data", {}).get("content", "")
                        if content:
                            append_message(sid, "assistant", content)
                    elif etype == "clarify":
                        questions = event.get("data", {}).get("questions", [])
                        if questions:
                            content = "我需要了解更多信息：\n\n" + "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
                            append_message(sid, "assistant", content)
                await asyncio.sleep(0)
        except Exception as e:
            yield sse_event("error", {"message": str(e)})
        yield sse_event("stream_end", {})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
# Agent 编排配置 (config.yaml role_models)
# ═══════════════════════════════════════

import yaml

@app.get("/api/agent/config")
def get_agent_config():
    """返回 config.yaml 中的 role_models"""
    return {
        "role_models": config.list_role_models(),
        "context_rounds": orchestrator.context_rounds,
        "available_providers": {
            name: {"base_url": info["base_url"], "models": info["models"]}
            for name, info in config.list_providers().items()
        },
    }


class AgentConfigUpdate(BaseModel):
    role_models: Optional[dict] = None
    context_rounds: Optional[int] = None


@app.put("/api/agent/config")
def put_agent_config(body: AgentConfigUpdate):
    """更新 agent 编排配置"""
    if body.role_models is not None:
        config_path = os.path.join(project_root, "config.yaml")
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        raw["role_models"] = body.role_models
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(raw, f, allow_unicode=True, default_flow_style=False)
        config.reload()
        orchestrator.initialize()

    if body.context_rounds is not None:
        orchestrator.context_rounds = max(2, min(body.context_rounds, 100))

    return {
        "ok": True,
        "role_models": config.list_role_models(),
        "context_rounds": orchestrator.context_rounds,
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
# 对话历史（Agent 模式 legacy）
# ═══════════════════════════════════════

@app.get("/api/history")
def get_history():
    return {"history": orchestrator.conversation_history}


# ═══════════════════════════════════════
# 启动
# ═══════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000, reload=False)
