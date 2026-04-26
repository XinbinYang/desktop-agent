import base64
import json
from typing import AsyncGenerator, List, Optional, Dict, Any
import httpx
from litellm import acompletion
from app.config import get_provider_for_model

class ModelRouter:
    def __init__(self, model_id: str):
        self.model_id = model_id
        info = get_provider_for_model(model_id)
        if info is None:
            raise ValueError(f"Unknown model: {model_id}")
        self.provider_name, self.provider = info

    async def _call_kimi_anthropic(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Kimi Code API 专用：使用 Anthropic 兼容端点获取 thinking 内容。"""
        api_base = self.provider.base_url.replace("/coding/v1", "/coding")
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.provider.api_key,
            "anthropic-version": "2023-06-01",
            "User-Agent": "Kilo-Code/1.0",
        }

        # 分离 system message，并转换 OpenAI 格式消息为 Anthropic 格式
        system_text = ""
        anthropic_messages = []
        for m in messages:
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
                # tool 结果在 Anthropic 中作为 user 消息的 tool_result block
                anthropic_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": m.get("tool_call_id", ""),
                        "content": m.get("content", ""),
                    }]
                })
            else:
                # user 消息直接传递
                anthropic_messages.append({
                    "role": role,
                    "content": m.get("content", ""),
                })

        payload: Dict[str, Any] = {
            "model": self.model_id,
            "max_tokens": max_tokens or 4096,
            "messages": anthropic_messages,
            "thinking": {"type": "enabled", "budget_tokens": 2048},
        }
        if system_text:
            payload["system"] = system_text
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
            resp.raise_for_status()
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

    async def _call_litellm(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False
    ):
        """内部辅助方法：统一调用 LiteLLM。"""
        if self.provider_name == "local":
            litellm_provider = "openai"
            api_base = self.provider.base_url
        else:
            litellm_provider = self.provider_name
            api_base = self.provider.base_url

        return await acompletion(
            model=f"{litellm_provider}/{self.model_id}",
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            api_base=api_base if api_base else None,
            api_key=self.provider.api_key if self.provider.api_key else None,
            stream=stream
        )

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False
    ) -> AsyncGenerator[str, None]:
        """统一的聊天完成接口。返回 JSON 字符串的流。"""
        if self.provider_name == "kimi":
            response = await self._call_kimi_anthropic(
                messages=messages, tools=tools, max_tokens=max_tokens
            )
            yield json.dumps(response) + "\n"
        else:
            response = await self._call_litellm(
                messages=messages, tools=tools, temperature=temperature,
                max_tokens=max_tokens, stream=stream
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
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """非流式调用，返回完整响应字典。"""
        if self.provider_name == "kimi":
            return await self._call_kimi_anthropic(
                messages=messages, tools=tools, max_tokens=max_tokens
            )
        response = await self._call_litellm(
            messages=messages, tools=tools, temperature=temperature,
            max_tokens=max_tokens, stream=False
        )
        return response.model_dump()

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
