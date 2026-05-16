import base64
import json
import logging
from typing import AsyncGenerator, List, Optional, Dict, Any
import httpx
from litellm import acompletion
from litellm.exceptions import BadRequestError
from app.config import get_provider_for_model

logger = logging.getLogger(__name__)


def _safe_content_shape(content: Any) -> Any:
    if isinstance(content, list):
        blocks = []
        for block in content:
            if isinstance(block, dict):
                summary = {"type": block.get("type")}
                if block.get("type") == "tool_use":
                    summary["name"] = block.get("name")
                    summary["input_keys"] = sorted((block.get("input") or {}).keys())
                elif block.get("type") == "tool_result":
                    summary["tool_use_id_present"] = bool(block.get("tool_use_id"))
                    summary["content_length"] = len(str(block.get("content", "")))
                elif block.get("type") == "text":
                    summary["text_length"] = len(str(block.get("text", "")))
                elif block.get("type") == "image":
                    source = block.get("source") or {}
                    summary["media_type"] = source.get("media_type")
                    summary["data_length"] = len(str(source.get("data", "")))
                blocks.append(summary)
            else:
                blocks.append({"type": type(block).__name__, "length": len(str(block))})
        return blocks
    return {"type": type(content).__name__, "length": len(str(content))}


def _safe_message_summary(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "role": message.get("role"),
            "content": _safe_content_shape(message.get("content", "")),
        }
        for message in messages
    ]

class ModelRouter:
    def __init__(self, model_id: str):
        self.model_id = model_id
        # Verify the model exists in config, but don't cache the provider —
        # api_key may be updated via Settings at runtime.  _get_provider()
        # re-reads load_config() so key changes take effect without a session
        # restart.
        if get_provider_for_model(model_id) is None:
            raise ValueError(f"Unknown model: {model_id}")

    def _get_provider(self):
        info = get_provider_for_model(self.model_id)
        if info is None:
            raise ValueError(f"Unknown model (config changed?): {self.model_id}")
        return info

    def _normalize_thinking_intensity(self, thinking_intensity: Optional[str]) -> str:
        if thinking_intensity in {"low", "medium", "high"}:
            return thinking_intensity
        return "medium"

    def _map_thinking_budget(self, thinking_intensity: Optional[str]) -> int:
        intensity = self._normalize_thinking_intensity(thinking_intensity)
        if intensity == "low":
            return 2048
        if intensity == "high":
            return 8192
        return 4096

    def _map_generic_temperature(self, thinking_intensity: Optional[str], base: float) -> float:
        intensity = self._normalize_thinking_intensity(thinking_intensity)
        if intensity == "low":
            return max(0.1, min(base, 0.3))
        if intensity == "high":
            return min(1.0, max(base, 0.7))
        return base

    async def _call_kimi_anthropic(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        max_tokens: Optional[int] = None,
        thinking_intensity: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Kimi Code API 专用：使用 Anthropic 兼容端点获取 thinking 内容。"""
        _name, provider = self._get_provider()
        api_base = provider.base_url.replace("/coding/v1", "/coding")
        headers = {
            "Content-Type": "application/json",
            "x-api-key": provider.api_key,
            "anthropic-version": "2023-06-01",
            "User-Agent": "Kilo-Code/1.0",
        }

        # 分离 system message，并转换 OpenAI 格式消息为 Anthropic 格式
        system_text = ""
        anthropic_messages: list[dict] = []
        i = 0
        while i < len(messages):
            m = messages[i]
            role = m.get("role")
            if role == "system":
                system_text = m.get("content", "")
            elif role == "assistant":
                content_blocks = []
                if m.get("content"):
                    content_blocks.append({"type": "text", "text": m["content"]})
                for tc in m.get("tool_calls", []):
                    func = tc.get("function", {})
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": func.get("name", ""),
                        "input": json.loads(func.get("arguments", "{}")),
                    })
                anthropic_messages.append({"role": "assistant", "content": content_blocks})
            elif role == "tool":
                # 合并连续的 tool 消息为一个 user 消息（Anthropic API 要求）
                tool_result_blocks = []
                max_tool_result_len = 8000
                while i < len(messages) and messages[i].get("role") == "tool":
                    content = messages[i].get("content") or ""
                    if len(content) > max_tool_result_len:
                        content = content[:max_tool_result_len] + f"\n\n[输出过长，已截断。原长度 {len(content)} 字符]"
                    tool_result_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": messages[i].get("tool_call_id", ""),
                        "content": content,
                    })
                    i += 1
                anthropic_messages.append({"role": "user", "content": tool_result_blocks})
                continue  # i 已在内层循环中递增
            else:
                # user 消息：处理 OpenAI vision 格式转换为 Anthropic 格式
                content = m.get("content", "")
                if isinstance(content, list):
                    anthropic_content = []
                    for block in content:
                        btype = block.get("type")
                        if btype == "text":
                            anthropic_content.append({"type": "text", "text": block.get("text", "")})
                        elif btype == "image_url":
                            url = block.get("image_url", {}).get("url", "")
                            if url.startswith("data:image/png;base64,"):
                                b64 = url.split(",")[1]
                                anthropic_content.append({
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": b64,
                                    }
                                })
                            else:
                                anthropic_content.append({"type": "text", "text": f"[Image: {url}]"})
                    # 合并连续的 user 消息，避免 Anthropic API 400
                    if anthropic_messages and anthropic_messages[-1].get("role") == "user":
                        existing = anthropic_messages[-1]["content"]
                        if isinstance(existing, list):
                            existing.extend(anthropic_content)
                        else:
                            anthropic_messages[-1]["content"] = [{"type": "text", "text": str(existing)}] + anthropic_content
                    else:
                        anthropic_messages.append({"role": "user", "content": anthropic_content})
                else:
                    # 合并连续的 user 消息
                    if anthropic_messages and anthropic_messages[-1].get("role") == "user":
                        existing = anthropic_messages[-1]["content"]
                        if isinstance(existing, list):
                            existing.append({"type": "text", "text": str(content)})
                        else:
                            anthropic_messages[-1]["content"] = str(existing) + "\n" + str(content)
                    else:
                        anthropic_messages.append({"role": "user", "content": content})
            i += 1

        # 防御性校验：Anthropic API 要求 messages 必须以 user 开始且角色交替
        if anthropic_messages and anthropic_messages[0].get("role") != "user":
            anthropic_messages.insert(0, {"role": "user", "content": "(history truncated)"})
        payload: Dict[str, Any] = {
            "model": self.model_id,
            "max_tokens": max_tokens or 4096,
            "messages": anthropic_messages,
        }
        if system_text:
            payload["system"] = system_text
        # Always enable extended thinking so the frontend can show a collapsible Thinking block
        payload["thinking"] = {
            "type": "enabled",
            "budget_tokens": self._map_thinking_budget(thinking_intensity),
        }

        if tools:
            anthropic_tools = []
            for t in tools:
                func = t.get("function", {})
                anthropic_tools.append({
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
                })
            payload["tools"] = anthropic_tools

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{api_base}/v1/messages", headers=headers, json=payload)
            # If the API rejects thinking+tools, retry without thinking
            if resp.status_code == 400 and tools:
                resp_text = ""
                try:
                    resp_text = (resp.text or "")[:2000]
                except Exception:
                    pass
                if "thinking" in resp_text.lower():
                    logger.info("Kimi API rejected thinking+tools, retrying without thinking")
                    payload.pop("thinking", None)
                    resp = await client.post(f"{api_base}/v1/messages", headers=headers, json=payload)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                resp_text2 = ""
                try:
                    resp_text2 = (resp.text or "")[:2000]
                except Exception:
                    pass
                logger.warning(
                    "Kimi API request failed: status=%s response_text=%s message_count=%s tool_count=%s message_summary=%s",
                    resp.status_code,
                    resp_text2,
                    len(anthropic_messages),
                    len(payload.get("tools", [])),
                    _safe_message_summary(anthropic_messages),
                )
                raise
            data = resp.json()

        # 解析 Anthropic 响应，转换为 OpenAI 格式
        thinking_text = ""
        text_content = ""
        tool_calls = []
        for block in data.get("content", []):
            btype = block.get("type")
            if btype == "thinking":
                thinking_text += block.get("thinking", "")
            elif btype == "text":
                text_content += block.get("text", "")
            elif btype == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {})),
                    },
                })

        openai_msg: Dict[str, Any] = {
            "role": "assistant",
            "content": text_content,
        }
        if thinking_text:
            openai_msg["reasoning_content"] = thinking_text
        if tool_calls:
            openai_msg["tool_calls"] = tool_calls

        return {
            "choices": [{
                "index": 0,
                "message": openai_msg,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }],
            "model": f"kimi/{self.model_id}",
            "usage": data.get("usage", {}),
        }

    def _is_deepseek(self) -> bool:
        provider_name, provider = self._get_provider()
        return provider_name == "deepseek" or provider.litellm_provider == "deepseek"

    async def _call_deepseek(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        thinking_intensity: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Call DeepSeek API directly, preserving reasoning_content in both directions.

        LiteLLM 1.52.0 does not recognise reasoning_content (a DeepSeek extension
        to the OpenAI message schema), so it drops the field during response
        deserialization.  DeepSeek thinking mode *requires* that reasoning_content
        be passed back in subsequent turns, so we bypass LiteLLM entirely.
        """
        _, provider = self._get_provider()
        api_base = provider.base_url.rstrip("/")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {provider.api_key}",
        }
        # Convert OpenAI-format tool definitions for the API
        api_tools = None
        if tools:
            api_tools = []
            for t in tools:
                func = t.get("function", {})
                api_tools.append({
                    "type": "function",
                    "function": {
                        "name": func.get("name", ""),
                        "description": func.get("description", ""),
                        "parameters": func.get("parameters", {"type": "object", "properties": {}}),
                    },
                })

        payload: Dict[str, Any] = {
            "model": self.model_id,
            "messages": messages,
            "temperature": self._map_generic_temperature(thinking_intensity, temperature),
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if api_tools:
            payload["tools"] = api_tools

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{api_base}/chat/completions", headers=headers, json=payload)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                resp_text = ""
                try:
                    resp_text = (resp.text or "")[:2000]
                except Exception:
                    pass
                logger.warning(
                    "DeepSeek API request failed: status=%s response_text=%s payload_summary=%s",
                    resp.status_code,
                    resp_text,
                    _safe_message_summary(messages),
                )
                raise
            return resp.json()

    async def _call_litellm(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        thinking_intensity: Optional[str] = None,
    ):
        """内部辅助方法：统一调用 LiteLLM。"""
        provider_name, provider = self._get_provider()
        litellm_provider = provider.litellm_provider or ("openai" if provider_name == "local" else provider_name)
        api_base = provider.base_url

        try:
            return await acompletion(
                model=f"{litellm_provider}/{self.model_id}",
                messages=messages,
                tools=tools,
                temperature=self._map_generic_temperature(thinking_intensity, temperature),
                max_tokens=max_tokens,
                api_base=api_base if api_base else None,
                api_key=provider.api_key if provider.api_key else None,
                stream=stream
            )
        except BadRequestError as e:
            error_text = str(e).lower()
            if "reasoning_content" in error_text and messages:
                # Distinguish "must be passed back" (DeepSeek thinking mode
                # requires it) from "not supported" (stale field on a provider
                # that rejects it).  Only strip for the latter.
                if "must be passed back" in error_text:
                    logger.warning(
                        "reasoning_content required but missing — LiteLLM likely "
                        "dropped it during message processing; retrying via direct "
                        "DeepSeek path"
                    )
                    return await self._call_deepseek(
                        messages=messages, tools=tools, temperature=temperature,
                    max_tokens=max_tokens, thinking_intensity=thinking_intensity,
                    )
                logger.warning(
                    "reasoning_content rejected by upstream, stripping from history and retrying once"
                )
                stripped = []
                for msg in messages:
                    if msg.get("role") == "assistant" and "reasoning_content" in msg:
                        msg = {k: v for k, v in msg.items() if k != "reasoning_content"}
                    stripped.append(msg)
                return await acompletion(
                    model=f"{litellm_provider}/{self.model_id}",
                    messages=stripped,
                    tools=tools,
                    temperature=self._map_generic_temperature(thinking_intensity, temperature),
                    max_tokens=max_tokens,
                    api_base=api_base if api_base else None,
                    api_key=provider.api_key if provider.api_key else None,
                    stream=stream
                )
            raise

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        thinking_intensity: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """统一的聊天完成接口。返回 JSON 字符串的流。"""
        provider_name = self._get_provider()[0]
        if provider_name == "kimi":
            response = await self._call_kimi_anthropic(
                messages=messages, tools=tools, max_tokens=max_tokens, thinking_intensity=thinking_intensity
            )
            yield json.dumps(response) + "\n"
        elif self._is_deepseek():
            response = await self._call_deepseek(
                messages=messages, tools=tools, temperature=temperature,
                max_tokens=max_tokens, thinking_intensity=thinking_intensity,
            )
            yield json.dumps(response) + "\n"
        else:
            response = await self._call_litellm(
                messages=messages, tools=tools, temperature=temperature,
                max_tokens=max_tokens, stream=stream, thinking_intensity=thinking_intensity
            )
            if stream:
                async for chunk in response:
                    yield json.dumps(chunk.model_dump()) + "\n"
            else:
                yield json.dumps(response.model_dump()) + "\n"

    async def chat_completion_non_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        thinking_intensity: Optional[str] = None,
    ) -> Dict[str, Any]:
        """非流式调用，返回完整响应字典。"""
        provider_name = self._get_provider()[0]
        if provider_name == "kimi":
            return await self._call_kimi_anthropic(
                messages=messages, tools=tools, max_tokens=max_tokens, thinking_intensity=thinking_intensity
            )
        if self._is_deepseek():
            return await self._call_deepseek(
                messages=messages, tools=tools, temperature=temperature,
                max_tokens=max_tokens, thinking_intensity=thinking_intensity,
            )
        response = await self._call_litellm(
            messages=messages, tools=tools, temperature=temperature,
            max_tokens=max_tokens, stream=False, thinking_intensity=thinking_intensity
        )
        dumped = response.model_dump(exclude_none=False)
        # litellm's ModelResponse.model_dump() may omit reasoning_content
        # (a non-standard OpenAI field used by DeepSeek thinking mode).
        rc = getattr(response.choices[0].message, "reasoning_content", None)
        if rc is not None:
            dumped["choices"][0]["message"]["reasoning_content"] = rc
        return dumped

    @staticmethod
    def encode_image_to_base64(image_path: str) -> str:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def build_vision_message(self, text: str, image_base64: str) -> Dict[str, Any]:
        """构建包含图片的 user message（OpenAI 格式，LiteLLM 会自动转换）。"""
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_base64}"}
                }
            ]
        }
