"""Sessions CRUD: stores sessions as JSON files in the sessions/ directory."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import re

SESSIONS_DIR = Path(__file__).parent.parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)


def _sanitize_filename(name: str) -> str:
    """Make string safe for filename, allowing Chinese and alphanumeric chars."""
    if not name:
        return "Unnamed"
    # Replace common invalid filename characters with underscore
    safe = re.sub(r'[\\/*?:"<>|]', '_', name)
    return safe.strip()[:60]


def _find_session_path(session_id: str) -> Optional[Path]:
    """Find the path for a session ID, whether old UUID-only format or new named format."""
    old_path = SESSIONS_DIR / f"{session_id}.json"
    if old_path.exists():
        return old_path
    
    matches = list(SESSIONS_DIR.glob(f"*_{session_id}.json"))
    if matches:
        return matches[0]
    return None


def _save_session(session: dict):
    """Write session to disk carefully, renaming the file if the title changed."""
    session_id = session["id"]
    name = session.get("name", "Unnamed")
    
    old_path = _find_session_path(session_id)
    
    safe_name = _sanitize_filename(name)
    new_path = SESSIONS_DIR / f"{safe_name}_{session_id}.json"
    
    with open(new_path, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)
        
    if old_path and old_path != new_path and old_path.exists():
        try:
            old_path.unlink()
        except:
            pass


def list_sessions() -> List[dict]:
    sessions = []
    for f in sorted(SESSIONS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
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


def create_session(name: str, system_prompt: str = "", params: Optional[dict] = None, mode: str = "chat") -> dict:
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
    _save_session(session)
    return session


def get_session(session_id: str) -> Optional[dict]:
    path = _find_session_path(session_id)
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def update_session(session_id: str, name: Optional[str] = None, system_prompt: Optional[str] = None,
                   params: Optional[dict] = None, mode: Optional[str] = None) -> Optional[dict]:
    session = get_session(session_id)
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
    _save_session(session)
    return session


def delete_session(session_id: str) -> bool:
    path = _find_session_path(session_id)
    if path and path.exists():
        path.unlink()
        return True
    return False


def append_message(session_id: str, role: str, content, usage: Optional[dict] = None,
                   model: Optional[str] = None, provider: Optional[str] = None) -> Optional[dict]:
    session = get_session(session_id)
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
    _save_session(session)
    return msg


def pop_last_messages(session_id: str, count: int = 2) -> Optional[str]:
    """Remove the last `count` messages, return the content of the last user message (for retry)."""
    session = get_session(session_id)
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
    _save_session(session)
    return last_user_content


def clear_messages(session_id: str) -> bool:
    session = get_session(session_id)
    if not session:
        return False
    session["messages"] = []
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_session(session)
    return True


def save_workflow(session_id: str, workflow_data: dict) -> bool:
    """Persist workflow into session (legacy compatible)."""
    session = get_session(session_id)
    if not session:
        return False
    # 确保 history 不丢失
    existing = session.get("workflow", {})
    if "history" not in workflow_data and "history" in existing:
        workflow_data["history"] = existing["history"]
    session["workflow"] = workflow_data
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_session(session)
    return True


def get_workflow(session_id: str) -> dict:
    """Load workflow data from session."""
    session = get_session(session_id)
    if not session:
        return {}
    return session.get("workflow", {})


def archive_current_workflow(session_id: str) -> bool:
    """将当前活跃的工作流归档到 history，清空 current。
    在新任务开始前调用，确保旧工作流不被覆盖。"""
    session = get_session(session_id)
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
    _save_session(session)
    return True


def update_workflow_step(session_id: str, step_id, step_data: dict) -> bool:
    """更新当前工作流中某个步骤的结果（用于 retry）。"""
    session = get_session(session_id)
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
    _save_session(session)
    return True

