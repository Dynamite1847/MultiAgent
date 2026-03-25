"""
LLM Client - 统一的 LLM 调用接口，支持多 Provider
所有 Provider 都通过 OpenAI 兼容接口调用
"""
import time
import json
import threading
from openai import OpenAI
from core.config import Config, ModelConfig
from core.logger import logger


class LLMCancelledError(Exception):
    """LLM 调用被取消"""
    pass


class LLMClient:
    """统一 LLM 调用客户端"""

    def __init__(self, config: Config):
        self.config = config
        self._clients: dict[str, OpenAI] = {}  # 缓存 provider -> client
        self.total_tokens = 0
        self.total_calls = 0
        # 每次任务的统计（可重置）
        self._task_tokens = 0
        self._task_calls = 0
        # 可选回调：每次 LLM 调用后触发
        self.on_call = None  # callback(call_info: dict)
        # 取消标志
        self._cancelled = threading.Event()

    def cancel(self):
        """取消当前/后续 LLM 调用"""
        self._cancelled.set()
        logger.info("LLM 调用已取消")

    def reset_cancel(self):
        """重置取消标志"""
        self._cancelled.clear()

    def _get_client(self, model_config: ModelConfig) -> OpenAI:
        """获取或创建 OpenAI 客户端（按 provider 缓存）"""
        key = f"{model_config.provider}:{model_config.base_url}"
        if key not in self._clients:
            self._clients[key] = OpenAI(
                api_key=model_config.api_key,
                base_url=model_config.base_url,
            )
            logger.debug(f"创建 LLM 客户端: {model_config.provider} → {model_config.base_url}")
        return self._clients[key]

    def call(
        self,
        messages: list[dict],
        role: str = "orchestrator",
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> str:
        """
        调用 LLM
        
        Args:
            messages: OpenAI 格式的消息列表
            role: 角色名称，用于查找对应模型
            temperature: 覆盖默认温度
            max_tokens: 覆盖默认最大 tokens
            response_format: 响应格式（如 {"type": "json_object"}）
        
        Returns:
            LLM 响应文本
        """
        model_config = self.config.get_model_for_role(role)
        client = self._get_client(model_config)

        temp = temperature if temperature is not None else model_config.temperature
        max_tok = max_tokens if max_tokens is not None else model_config.max_tokens

        logger.debug(
            f"LLM调用: {model_config.provider}/{model_config.model} "
            f"(temperature={temp})",
            indent=1,
        )

        # ── 详细日志：发送的消息 ──
        for msg in messages:
            role_label = msg['role'].upper()
            content_preview = msg['content']
            if role_label == "SYSTEM":
                lines = content_preview.count('\n') + 1
                logger.debug(f"├─ [SYSTEM PROMPT] ({len(content_preview)}字符, {lines}行)", indent=1)
                # 完整记录 system prompt（按行缩进）
                for line in content_preview.split('\n')[:50]:  # 最多50行
                    logger.debug(f"│    {line}", indent=1)
                if lines > 50:
                    logger.debug(f"│    ... (省略 {lines - 50} 行)", indent=1)
            else:
                logger.debug(f"├─ [{role_label}] {content_preview[:300]}{'...' if len(str(content_preview)) > 300 else ''}", indent=1)

        start_time = time.time()

        kwargs = {
            "model": model_config.model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": max_tok,
        }
        if response_format:
            kwargs["response_format"] = response_format

        try:
            # 检查取消标志
            if self._cancelled.is_set():
                raise LLMCancelledError("任务已取消")
            response = client.chat.completions.create(**kwargs)
            # 调用完成后再检查一次
            if self._cancelled.is_set():
                raise LLMCancelledError("任务已取消")
        except Exception as e:
            logger.error(f"LLM调用失败: {e}")
            raise

        elapsed = time.time() - start_time
        content = response.choices[0].message.content or ""

        # 统计 token
        usage = response.usage
        prompt_tokens = 0
        completion_tokens = 0
        if usage:
            prompt_tokens = usage.prompt_tokens or 0
            completion_tokens = usage.completion_tokens or 0
        tokens_used = prompt_tokens + completion_tokens
        self.total_tokens += tokens_used
        self._task_tokens += tokens_used
        self.total_calls += 1
        self._task_calls += 1

        logger.debug(
            f"响应: {len(content)}字符, "
            f"tokens: {prompt_tokens}(prompt)+{completion_tokens}(completion)={tokens_used}, "
            f"耗时{elapsed:.1f}s",
            indent=1,
        )
        # ── 详细日志：完整响应内容 ──
        logger.debug(f"├─ [LLM返回] {content[:500]}{'...' if len(content) > 500 else ''}", indent=1)

        # ── 回调通知 ──
        if self.on_call:
            try:
                self.on_call({
                    "role": role,
                    "model": f"{model_config.provider}/{model_config.model}",
                    "messages": messages,
                    "response": content,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "elapsed": round(elapsed, 2),
                })
            except Exception:
                pass  # 回调失败不影响主流程

        return content

    def call_json(
        self,
        messages: list[dict],
        role: str = "orchestrator",
        temperature: float | None = None,
    ) -> dict:
        """
        调用 LLM 并解析 JSON 响应。
        根据 Provider 的 json_format_mode 自动选择:
        - chat_completions: 标准 response_format: json_object (OpenAI/Anthropic/Google)
        - responses_api:    火山方舟 Responses API text.format (豆包)
        - prompt:           Prompt 指令引导 + 后处理 (通用兜底)
        """
        model_config = self.config.get_model_for_role(role)
        mode = model_config.json_format_mode

        if mode == "chat_completions":
            # ── 标准 Chat Completions API 的 response_format ──
            logger.debug(
                f"使用 Chat Completions JSON mode ({model_config.provider})",
                indent=1,
            )
            content = self.call(
                messages=messages,
                role=role,
                temperature=temperature,
                response_format={"type": "json_object"},
            )

        elif mode == "responses_api":
            # ── 火山方舟 Responses API (豆包) ──
            logger.debug(
                f"使用 Responses API JSON mode ({model_config.provider})",
                indent=1,
            )
            content = self._call_responses_api(
                messages=messages,
                model_config=model_config,
                temperature=temperature,
            )

        else:
            # ── Prompt 引导模式 (兜底) ──
            logger.debug(
                f"使用 Prompt 引导 JSON ({model_config.provider})",
                indent=1,
            )
            patched_messages = list(messages)
            if patched_messages:
                last = patched_messages[-1].copy()
                last["content"] = (
                    last["content"]
                    + "\n\n请务必只输出合法的 JSON，不要包含任何其他文字、解释或 markdown 标记。"
                )
                patched_messages[-1] = last

            content = self.call(
                messages=patched_messages,
                role=role,
                temperature=temperature,
            )

        return self._extract_json(content)

    def _call_responses_api(
        self,
        messages: list[dict],
        model_config: ModelConfig,
        temperature: float | None = None,
    ) -> str:
        """
        调用火山方舟 Responses API（豆包原生结构化输出）
        使用 client.responses.create + text.format
        """
        client = self._get_client(model_config)
        temp = temperature if temperature is not None else model_config.temperature

        start_time = time.time()

        # 将 messages 转换为 Responses API 的 input 格式
        input_messages = []
        for msg in messages:
            input_messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })

        try:
            response = client.responses.create(
                model=model_config.model,
                input=input_messages,
                text={"format": {"type": "json_object"}},
                temperature=temp,
            )
        except Exception as e:
            logger.error(f"Responses API 调用失败: {e}")
            raise

        elapsed = time.time() - start_time

        # 提取输出内容
        content = ""
        if response.output:
            for item in response.output:
                if hasattr(item, "text"):
                    content = item.text
                    break
                elif hasattr(item, "content") and item.content:
                    # 兼容不同响应格式
                    for part in item.content:
                        if hasattr(part, "text"):
                            content = part.text
                            break

        # 统计 token
        prompt_tokens = 0
        completion_tokens = 0
        if hasattr(response, "usage") and response.usage:
            prompt_tokens = getattr(response.usage, "input_tokens", 0) or 0
            completion_tokens = getattr(response.usage, "output_tokens", 0) or 0
        tokens_used = prompt_tokens + completion_tokens
        self.total_tokens += tokens_used
        self._task_tokens += tokens_used
        self.total_calls += 1
        self._task_calls += 1

        logger.debug(
            f"响应: {len(content)}字符, "
            f"tokens: {prompt_tokens}(prompt)+{completion_tokens}(completion)={tokens_used}, "
            f"耗时{elapsed:.1f}s",
            indent=1,
        )
        # ── 详细日志：完整响应内容 ──
        logger.debug(f"├─ [LLM返回] {content[:500]}{'...' if len(content) > 500 else ''}", indent=1)

        return content

    def _extract_json(self, content: str) -> dict:
        """从 LLM 响应中提取 JSON，支持多种格式"""
        # 1. 直接解析
        content_stripped = content.strip()
        try:
            return json.loads(content_stripped)
        except json.JSONDecodeError:
            pass

        # 2. 从 ```json ... ``` 代码块中提取
        if "```json" in content:
            try:
                json_str = content.split("```json")[1].split("```")[0].strip()
                return json.loads(json_str)
            except (json.JSONDecodeError, IndexError):
                pass

        # 3. 从 ``` ... ``` 代码块中提取
        if "```" in content:
            try:
                json_str = content.split("```")[1].split("```")[0].strip()
                return json.loads(json_str)
            except (json.JSONDecodeError, IndexError):
                pass

        # 4. 用括号匹配提取第一个完整的 JSON 对象
        first_brace = content.find("{")
        if first_brace != -1:
            depth = 0
            in_string = False
            escape = False
            for i in range(first_brace, len(content)):
                ch = content[i]
                if escape:
                    escape = False
                    continue
                if ch == '\\':
                    escape = True
                    continue
                if ch == '"' and not escape:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(content[first_brace:i + 1])
                        except json.JSONDecodeError:
                            break

        logger.error(f"无法从 LLM 响应中提取 JSON:\n{content[:500]}")
        raise ValueError("LLM 返回的内容无法解析为 JSON")

    def reset_task_stats(self):
        """重置当前任务的 token 统计"""
        self._task_tokens = 0
        self._task_calls = 0

    def get_task_stats(self) -> dict:
        """获取当前任务的调用统计"""
        return {
            "task_calls": self._task_calls,
            "task_tokens": self._task_tokens,
        }

    def get_stats(self) -> dict:
        """获取全局调用统计"""
        return {
            "total_calls": self.total_calls,
            "total_tokens": self.total_tokens,
        }
