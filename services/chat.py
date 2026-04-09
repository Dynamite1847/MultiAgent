"""Core chat logic: context assembly, streaming, and response persistence."""
import json
import asyncio
import logging
from typing import AsyncIterator, List, Optional

from services.provider_config import load_config, get_provider_config
from services.providers.registry import get_provider
from services.sessions import get_session, append_message, update_session
from services.tokens import (
    count_messages_tokens,
    trim_messages_by_rounds,
    trim_messages_by_tokens,
    truncate_text_by_tokens,
    estimate_tokens
)
from memory.observer import ObserverMemory

logger = logging.getLogger(__name__)


async def generate_title(session_id: str, user_text: str, assistant_text: str, user_id: str = "default"):
    """Use DeepSeek (openai provider) to summarize Q+A into a short title, then update session."""
    try:
        cfg = load_config()
        # Use openai provider (configured as DeepSeek) for cheap title generation
        ds_cfg = get_provider_config("openai")
        if not ds_cfg.get("api_key") or not ds_cfg.get("base_url"):
            logger.info("No openai/deepseek provider configured, skipping auto-title.")
            return

        ds_model = (ds_cfg.get("models") or ["deepseek-chat"])[0]
        # If the model is a reasoner model, use deepseek-chat instead (cheaper/faster for titles)
        if "reasoner" in ds_model:
            ds_model = "deepseek-chat"

        provider = get_provider("openai", ds_cfg)

        title_prompt = (
            "根据用户和大模型的对话，用不超过15个字生成一个简短的中文标题，标题要体现出用户在和ai讨论什么。"
            "只输出标题文字本身，不要加引号、不要解释。\n\n"
            f"用户: {user_text[:300]}\n"
            f"助手: {assistant_text[:300]}"
        )

        full_title = []
        async for chunk in provider.stream_chat(
            messages=[{"role": "user", "content": title_prompt}],
            system_prompt="你是一个标题生成器。",
            model=ds_model,
            max_tokens=30,
            temperature=0.3,
            top_p=1.0,
        ):
            delta = chunk.get("delta", "")
            if delta:
                full_title.append(delta)

        title = "".join(full_title).strip().strip('"').strip("'").strip("《》")
        if title:
            update_session(session_id, user_id=user_id, name=title)
            logger.info(f"Auto-title update successful: {title}")
    except Exception as e:
        logger.warning(f"Auto-title failed for session {session_id}: {e}")


def build_content(text: str, files: Optional[List[dict]] = None):
    """Build message content, potentially multimodal."""
    if not files:
        return text

    parts = []
    for f in files:
        if f["type"] == "image":
            parts.append({
                "type": "image_url",
                "image_url": {"url": f["data_url"]}
            })
        elif f["type"] == "document":
            doc_text = f"[附件: {f['filename']}]\n{f['text']}"
            parts.append({"type": "text", "text": doc_text})

    if text:
        parts.append({"type": "text", "text": text})

    if len(parts) == 1 and parts[0].get("type") == "text":
        return parts[0]["text"]
    return parts


def assemble_context(
    session: dict,
    new_user_content,
    context_rounds: int = 10,
    context_limit: int = 60000,
    max_single_message_tokens: int = 30000,
) -> List[dict]:
    """Build the messages list for the API call using Observer Memory.

    Session messages are NEVER modified. If context is too large,
    ObserverMemory builds [summary] + [recent N rounds].
    """
    history = session.get("messages", [])
    raw_messages = [{"role": m["role"], "content": m["content"]}
                    for m in history if m["role"] in ("user", "assistant")]

    if new_user_content:
        if not raw_messages or raw_messages[-1]["content"] != new_user_content:
            raw_messages.append({"role": "user", "content": new_user_content})

    # Merge consecutive messages of the same role
    messages = []
    for m in raw_messages:
        if not messages:
            messages.append(m)
            continue
        last_m = messages[-1]
        if last_m["role"] == m["role"]:
            c1 = last_m["content"]
            c2 = m["content"]
            if isinstance(c1, str) and isinstance(c2, str):
                last_m["content"] = c1 + "\n\n" + c2
            else:
                l1 = [{"type": "text", "text": c1}] if isinstance(c1, str) else c1
                l2 = [{"type": "text", "text": c2}] if isinstance(c2, str) else c2
                last_m["content"] = l1 + l2
        else:
            messages.append(m)

    # 使用 Observer Memory 构建上下文
    observer_summary = session.get("observer_summary")

    context = ObserverMemory.build_context(
        messages=messages,
        observer_summary=observer_summary,
        context_rounds=context_rounds,
    )

    # Truncate individual oversized messages
    for msg in context:
        content = msg.get("content", "")
        if isinstance(content, str):
            tokens = estimate_tokens(content)
            if tokens > max_single_message_tokens:
                logger.warning(
                    f"Truncating {msg['role']} message from ~{tokens} to ~{max_single_message_tokens} tokens"
                )
                msg["content"] = truncate_text_by_tokens(content, max_single_message_tokens)
        elif isinstance(content, list):
            for part in content:
                if part.get("type") == "text":
                    text = part.get("text", "")
                    tokens = estimate_tokens(text)
                    if tokens > max_single_message_tokens:
                        part["text"] = truncate_text_by_tokens(text, max_single_message_tokens)

    total = count_messages_tokens(context)
    logger.info(f"Context assembled: {len(context)} messages, ~{total} tokens "
               f"(OM: {'有摘要' if observer_summary else '无摘要'})")
    return context


async def stream_chat_response(
    session_id: str,
    user_message: str,
    files: Optional[List[dict]] = None,
    provider_name: Optional[str] = None,
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    max_tokens: int = 8096,
    temperature: float = 1.0,
    top_p: float = 1.0,
    frequency_penalty: float = 0.0,
    context_rounds: int = 10,
    user_id: str = "default"
) -> AsyncIterator[str]:
    """
    Yields SSE-formatted strings. Saves the full response to session on completion.
    """
    cfg = load_config()

    # Resolve provider and model
    if not provider_name:
        provider_name = cfg.get("default_provider", "anthropic")
    if not model:
        model = cfg.get("default_model", "claude-sonnet-4-5")

    provider_cfg = get_provider_config(provider_name)
    if not provider_cfg.get("api_key"):
        yield f"data: {json.dumps({'error': f'Provider {provider_name} has no API key configured.'})}\n\n"
        return

    session = get_session(session_id, user_id=user_id)
    if not session:
        yield f"data: {json.dumps({'error': 'Session not found.'})}\n\n"
        return

    # Check if this is the first message (for auto-title later)
    is_first_message = len(session.get("messages", [])) == 0

    # Resolve system prompt
    effective_system = system_prompt
    if effective_system is None:
        effective_system = session.get("system_prompt") or cfg.get("global_system_prompt", "")

    # Build user content (multimodal)
    user_content = build_content(user_message, files)

    # Persist user message FIRST, so it is never lost even if API call fails
    append_message(session_id, "user", user_content, user_id=user_id)

    # Re-fetch session so assemble_context has the newly appended message
    session = get_session(session_id, user_id=user_id)

    # ── Observer Memory: 检查并压缩 ──
    context_limit = cfg.get("context_limit", 60000)
    om_threshold = cfg.get("om_threshold", 0.7)
    all_messages = session.get("messages", [])
    observer_summary = session.get("observer_summary")

    om_event = None  # 用于前端展示的 OM 压缩事件

    if ObserverMemory.should_compact(all_messages, observer_summary,
                                      context_limit, om_threshold, context_rounds):
        try:
            from core.llm_client import LLMClient
            from core.config import Config
            llm = LLMClient(Config())
            new_summary = ObserverMemory.compact(
                messages=all_messages,
                llm_client=llm,
                role="observer",
                existing_summary=observer_summary,
                context_rounds=context_rounds,
            )
            if new_summary and new_summary.get("content"):
                from services.sessions import save_observer_summary
                save_observer_summary(session_id, new_summary, user_id=user_id)
                session = get_session(session_id, user_id=user_id)
                # 构造前端展示事件
                om_event = {
                    "version": new_summary.get("version", 1),
                    "compressed_count": new_summary.get("compressed_up_to", 0),
                    "active_count": len(all_messages) - new_summary.get("compressed_up_to", 0),
                    "summary_preview": new_summary["content"][:150] + ("..." if len(new_summary["content"]) > 150 else ""),
                }
        except Exception as e:
            logger.warning(f"OM compact 失败，继续使用原始上下文: {e}")

    # Assemble context (with OM summary if available)
    messages = assemble_context(
        session=session,
        new_user_content=user_content,
        context_rounds=context_rounds or cfg.get("context_rounds", 10),
        context_limit=context_limit,
        max_single_message_tokens=cfg.get("max_single_message_tokens", 30000),
    )

    provider = get_provider(provider_name, provider_cfg)
    full_response = []
    usage = None

    # 先发送 OM 压缩事件（如果有）
    if om_event:
        yield f"data: {json.dumps({'observer_memory': om_event})}\n\n"

    try:
        async for chunk in provider.stream_chat(
            messages=messages,
            system_prompt=effective_system,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            frequency_penalty=frequency_penalty
        ):
            delta = chunk.get("delta", "")
            finish_reason = chunk.get("finish_reason")
            chunk_usage = chunk.get("usage")
            status = chunk.get("status")

            # Forward status events (e.g. "thinking") to frontend
            if status:
                yield f"data: {json.dumps({'status': status})}\n\n"

            if delta:
                full_response.append(delta)
                yield f"data: {json.dumps({'delta': delta, 'finish_reason': None})}\n\n"

            if chunk_usage:
                usage = chunk_usage

            if finish_reason:
                payload = {
                    "delta": "",
                    "finish_reason": finish_reason,
                    "usage": usage
                }
                yield f"data: {json.dumps(payload)}\n\n"

    except asyncio.CancelledError:
        logger.warning("Stream cancelled by client (asyncio.CancelledError). Saving partial output...")
        full_text = "".join(full_response)
        if full_text:
            try:
                append_message(
                    session_id, "assistant", full_text,
                    usage=usage, model=model, provider=provider_name, user_id=user_id
                )
            except Exception as e:
                logger.error(f"Failed to persist partial message on cancel: {e}", exc_info=True)
        raise

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in stream_chat_response: {error_msg}", exc_info=True)
        yield f"data: {json.dumps({'error': error_msg})}\n\n"
        # On normal exception, we also want to save partial text
        full_text = "".join(full_response)
        if full_text:
            try:
                append_message(
                    session_id, "assistant", full_text,
                    usage=usage, model=model, provider=provider_name, user_id=user_id
                )
            except Exception as persist_e:
                logger.error(f"Failed to persist partial message on error: {persist_e}", exc_info=True)
                
    else:
        # On clean exit without exceptions
        full_text = "".join(full_response)
        if full_text:
            try:
                append_message(
                    session_id, "assistant", full_text,
                    usage=usage, model=model, provider=provider_name, user_id=user_id
                )
            except Exception as e:
                logger.error(f"Failed to persist complete message: {e}", exc_info=True)
        else:
            # API returned 200 but stream had zero content – likely a provider issue
            logger.warning(f"Empty response from provider {provider_name} model={model} for session {session_id}")
            yield f"data: {json.dumps({'error': f'API 返回了空的响应，请重试。可能是服务商（{provider_name}）临时异常。'})}\n\n"

    # Auto-title: on first message, use DeepSeek to generate a concise title
    if is_first_message and full_text:
        user_text = user_message if isinstance(user_message, str) else str(user_message)
        asyncio.create_task(generate_title(session_id, user_text, full_text, user_id=user_id))

    yield "data: [DONE]\n\n"
