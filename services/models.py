from pydantic import BaseModel
from typing import Optional, List, Any


class Message(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: Any  # str or list[dict] for multimodal


class ChatParams(BaseModel):
    max_tokens: int = 8096
    temperature: float = 1.0
    top_p: float = 1.0
    frequency_penalty: float = 0.0


class ChatRequest(BaseModel):
    session_id: str
    message: str
    files: Optional[List[dict]] = None  # [{type:"image"|"document", data:..., name:...}]
    provider: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    params: Optional[ChatParams] = None
    context_strategy: Optional[str] = None  # "rounds" | "tokens"
    context_rounds: Optional[int] = None
    context_token_threshold: Optional[int] = None


class SessionCreate(BaseModel):
    name: str
    system_prompt: Optional[str] = None
    params: Optional[dict] = None


class SessionUpdate(BaseModel):
    name: Optional[str] = None
    system_prompt: Optional[str] = None
    params: Optional[dict] = None
    mode: Optional[str] = None


class ConfigUpdate(BaseModel):
    config: dict


class TokenCountRequest(BaseModel):
    messages: List[Message]
    model: Optional[str] = None
