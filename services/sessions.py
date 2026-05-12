"""Sessions CRUD: stores sessions as JSON files in the sessions/ directory."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import re

SESSIONS_BASE = Path(__file__).parent.parent / "sessions"
SESSIONS_BASE.mkdir(exist_ok=True)


def _user_sessions_dir(user_id: str = "default") -> Path:
    """Get per-user session directory, creating it if needed."""
    d = SESSIONS_BASE / user_id
    d.mkdir(exist_ok=True)
    return d


def _sanitize_filename(name: str) -> str:
    """Make string safe for filename, allowing Chinese and alphanumeric chars."""
    if not name:
        return "Unnamed"
    # Replace common invalid filename characters with underscore
    safe = re.sub(r'[\\/*?:"<>|]', '_', name)
    return safe.strip()[:60]


def _find_session_path(session_id: str, user_id: str = "default") -> Optional[Path]:
    """Find the path for a session ID, whether old UUID-only format or new named format."""
    # If a specific user_id is given, search only that directory
    if user_id != "default":
        user_dir = _user_sessions_dir(user_id)
        found = _search_in_dir(user_dir, session_id)
        if found:
            return found

    # Fallback: search ALL user subdirectories (for callers that don't know user_id)
    for d in SESSIONS_BASE.iterdir():
        if d.is_dir():
            found = _search_in_dir(d, session_id)
            if found:
                return found

    # Legacy: check base dir itself
    found = _search_in_dir(SESSIONS_BASE, session_id)
    return found


def _search_in_dir(directory: Path, session_id: str) -> Optional[Path]:
    """Search for a session file in a specific directory."""
    old_path = directory / f"{session_id}.json"
    if old_path.exists():
        return old_path
    matches = list(directory.glob(f"*_{session_id}.json"))
    if matches:
        return matches[0]
    # 手动复制/重命名的会话文件可能不再符合「标题_uuid.json」命名规则。
    # 列表接口仍能读到这些文件，但详情接口按文件名查找会失败；这里兜底检查 JSON 内部 id。
    for path in directory.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("id") == session_id:
                return path
        except Exception:
            continue
    return None


def _save_session(session: dict, user_id: str = "default"):
    """Write session to disk carefully, renaming the file if the title changed."""
    session_id = session["id"]
    name = session.get("name", "Unnamed")
    
    old_path = _find_session_path(session_id, user_id)
    
    # 如果找到了已有的会话文件，保持它在原来的目录（防止因为有些调用没传 user_id 导致被移入 default）
    if old_path:
        user_dir = old_path.parent
    else:
        user_dir = _user_sessions_dir(user_id)
    
    safe_name = _sanitize_filename(name)
    new_path = user_dir / f"{safe_name}_{session_id}.json"
    
    with open(new_path, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)
        
    if old_path and old_path != new_path and old_path.exists():
        try:
            old_path.unlink()
        except:
            pass


def list_sessions(user_id: str = "default") -> List[dict]:
    sessions = []
    user_dir = _user_sessions_dir(user_id)
    for f in sorted(user_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            sessions.append({
                "id": data["id"],
                "name": data["name"],
                "mode": data.get("mode", "chat"),
                "created_at": data["created_at"],
                "updated_at": data["updated_at"],
                "message_count": len(data.get("messages", [])),
                "system_prompt": data.get("system_prompt", "")
            })
        except Exception:
            pass
    return sessions


def create_session(name: str, system_prompt: str = "", params: Optional[dict] = None, mode: str = "chat", user_id: str = "default") -> dict:
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    clean_params = params.copy() if params else {}
    if "system_prompt" in clean_params:
        del clean_params["system_prompt"]
        
    session = {
        "id": session_id,
        "name": name,
        "mode": mode,
        "system_prompt": system_prompt,
        "params": clean_params,
        "created_at": now,
        "updated_at": now,
        "messages": []
    }
    _save_session(session, user_id)
    return session


def get_session(session_id: str, user_id: str = "default") -> Optional[dict]:
    path = _find_session_path(session_id, user_id)
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def update_session(session_id: str, name: Optional[str] = None, system_prompt: Optional[str] = None,
                   params: Optional[dict] = None, mode: Optional[str] = None, user_id: str = "default") -> Optional[dict]:
    session = get_session(session_id, user_id)
    if not session:
        return None
    if name is not None:
        session["name"] = name
    if mode is not None:
        session["mode"] = mode
    if system_prompt is not None:
        session["system_prompt"] = system_prompt
    if params is not None:
        clean_params = params.copy()
        if "system_prompt" in clean_params:
            del clean_params["system_prompt"]
        session["params"] = clean_params
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_session(session, user_id)
    return session


def delete_session(session_id: str, user_id: str = "default") -> bool:
    path = _find_session_path(session_id, user_id)
    if path and path.exists():
        path.unlink()
        return True
    return False


def append_message(session_id: str, role: str, content, usage: Optional[dict] = None,
                   model: Optional[str] = None, provider: Optional[str] = None, user_id: str = "default") -> Optional[dict]:
    session = get_session(session_id, user_id)
    if not session:
        return None
    msg = {
        "role": role,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    if usage:
        msg["usage"] = usage
    if model:
        msg["model"] = model
    if provider:
        msg["provider"] = provider
    session["messages"].append(msg)
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_session(session, user_id)
    return msg


def pop_last_messages(session_id: str, count: int = 2, user_id: str = "default") -> Optional[str]:
    """Remove the last `count` messages, return the content of the last user message (for retry)."""
    session = get_session(session_id, user_id)
    if not session:
        return None
    msgs = session.get("messages", [])
    if not msgs:
        return None
    # Find last user message before popping
    last_user_content = None
    for msg in reversed(msgs):
        if msg["role"] == "user":
            last_user_content = msg["content"]
            break
    # Pop
    session["messages"] = msgs[:-count] if count <= len(msgs) else []
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_session(session, user_id)
    return last_user_content


def clear_messages(session_id: str, user_id: str = "default") -> bool:
    session = get_session(session_id, user_id)
    if not session:
        return False
    session["messages"] = []
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_session(session, user_id)
    return True


def save_workflow(session_id: str, workflow_data: dict, user_id: str = "default") -> bool:
    """Persist workflow into session (legacy compatible)."""
    session = get_session(session_id, user_id)
    if not session:
        return False
    # 确保 history 不丢失
    existing = session.get("workflow", {})
    if "history" not in workflow_data and "history" in existing:
        workflow_data["history"] = existing["history"]
    session["workflow"] = workflow_data
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_session(session, user_id)
    return True


def get_workflow(session_id: str, user_id: str = "default") -> dict:
    """Load workflow data from session."""
    session = get_session(session_id, user_id)
    if not session:
        return {}
    return session.get("workflow", {})


def archive_current_workflow(session_id: str, user_id: str = "default") -> bool:
    """将当前活跃的工作流归档到 history，清空 current。
    在新任务开始前调用，确保旧工作流不被覆盖。"""
    session = get_session(session_id, user_id)
    if not session:
        return False
    wf = session.get("workflow", {})
    history = wf.get("history", [])

    # 如果当前有活跃的工作流（有 plan 且有已执行的步骤结果），归档
    current_plan = wf.get("plan")
    current_steps = wf.get("steps", [])
    has_executed_steps = any(
        s.get("status") in ("completed", "failed") for s in current_steps
    ) if current_steps else False
    if current_plan and has_executed_steps:
        history.append({
            "plan": current_plan,
            "steps": current_steps,
            "status": wf.get("status", "archived"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    session["workflow"] = {
        "plan": None,
        "steps": [],
        "status": "idle",
        "history": history,
    }
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_session(session, user_id)
    return True


def update_workflow_step(session_id: str, step_id, step_data: dict, user_id: str = "default") -> bool:
    """更新当前工作流中某个步骤的结果（用于 retry）。"""
    session = get_session(session_id, user_id)
    if not session:
        return False
    wf = session.get("workflow", {})
    steps = wf.get("steps", [])
    found = False
    for i, s in enumerate(steps):
        if s.get("step_id") == step_id:
            steps[i] = {**s, **step_data}
            found = True
            break
    if not found:
        steps.append(step_data)
    wf["steps"] = steps
    session["workflow"] = wf
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_session(session, user_id)
    return True


# ═══════════════════════════════════════
# Agent Loop Activity 持久化
# ═══════════════════════════════════════

def save_agent_activity(session_id: str, activity: dict, user_id: str = "default") -> bool:
    """
    保存 Agent Loop 的工具调用活动到 session。
    activity: {
        tool_calls: [{id, name, arguments, status, result, elapsed, turn}],
        turns: int,
        elapsed: float,
        total_tokens: int,
        total_tool_calls: int,
    }
    """
    session = get_session(session_id, user_id)
    if not session:
        return False

    # 累积到 agent_history 数组
    history = session.get("agent_history", [])
    activity["timestamp"] = datetime.now(timezone.utc).isoformat()
    history.append(activity)

    session["agent_history"] = history
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_session(session, user_id)
    return True


def get_agent_activity(session_id: str, user_id: str = "default") -> list:
    """加载 session 的 Agent Loop 历史活动。"""
    session = get_session(session_id, user_id)
    if not session:
        return []
    return session.get("agent_history", [])


# ═══════════════════════════════════════
# Observer Memory 持久化
# ═══════════════════════════════════════

def save_observer_summary(session_id: str, summary: dict, user_id: str = "default") -> bool:
    """保存 Observer Memory 摘要到 session（独立字段，不影响 messages）。

    summary: {
        content: str,             摘要文本
        compressed_up_to: int,    已压缩到第几条消息
        message_count: int,       压缩时的总消息数
        created_at: str,          创建时间
        version: int,             版本号（每次压缩递增）
    }
    """
    session = get_session(session_id, user_id)
    if not session:
        return False
    session["observer_summary"] = summary
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_session(session, user_id)
    return True


def get_observer_summary(session_id: str, user_id: str = "default") -> dict | None:
    """读取 session 的 Observer Memory 摘要。"""
    session = get_session(session_id, user_id)
    if not session:
        return None
    return session.get("observer_summary")
