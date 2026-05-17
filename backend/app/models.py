import asyncio
import base64
import json
import logging
from typing import AsyncGenerator, List, Optional, Dict, Any
import httpx
from litellm import acompletion
from litellm.exceptions import BadRequestError
from app.config import get_provider_for_model, load_config

logger = logging.getLogger(__name__)

RETRYABLE_PROVIDER_STATUSES = {429, 500, 502, 503, 504}
KIMI_RETRY_DELAYS_SECONDS = (2.0, 5.0, 10.0)
THINKING_INTENSITIES = {"low", "medium", "high"}
DEFAULT_THINKING_BUDGETS = {
    "low": 2048,
    "medium": 4096,
    "high": 6144,
}
DEFAULT_REASONING_EFFORTS = {
    "low": "low",
    "medium": "medium",
    "high": "high",
}
KIMI_STREAM_FIRST_EVENT_TIMEOUT_SECONDS = 8
KIMI_STREAM_IDLE_TIMEOUT_SECONDS = 45


def _is_retryable_provider_status(status_code: int) -> bool:
    return status_code in RETRYABLE_PROVIDER_STATUSES


def _friendly_kimi_error(status_code: int, body: str) -> str:
    compact_body = " ".join((body or "").split())[:1000]
    if status_code == 429:
        return (
            "Kimi API is temporarily overloaded or rate-limited (429). "
            "The settings connection test can still pass because this failure happens during generation. "
            "Please retry shortly or switch this session to another model. "
            f"Raw response: {compact_body}"
        )
    return f"Kimi API request failed: {status_code} {compact_body}"


def _retry_delay_seconds(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("retry-after") or response.headers.get("Retry-After")
    if retry_after:
        try:
            return min(30.0, max(1.0, float(retry_after)))
        except ValueError:
            pass
    return KIMI_RETRY_DELAYS_SECONDS[attempt]


def _is_empty_openai_message(message: Dict[str, Any]) -> bool:
    return (
        not str(message.get("content") or "").strip()
        and not message.get("tool_calls")
        and not str(message.get("reasoning_content") or "").strip()
    )


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
        if thinking_intensity in THINKING_INTENSITIES:
            return thinking_intensity
        return "medium"

    def _thinking_policy(self) -> Dict[str, Any]:
        provider_name, provider = self._get_provider()
        policies = getattr(load_config().settings, "thinking_policy_by_provider", {}) or {}
        for key in (provider_name, provider.litellm_provider):
            if key and isinstance(policies.get(key), dict):
                return policies[key]
        return {}

    def _policy_map(self, key: str) -> Dict[str, Any]:
        value = self._thinking_policy().get(key)
        return value if isinstance(value, dict) else {}

    def _map_thinking_budget(self, thinking_intensity: Optional[str], max_tokens: Optional[int] = None) -> int:
        intensity = self._normalize_thinking_intensity(thinking_intensity)
        configured = self._policy_map("budget_tokens") or self._policy_map("budgets")
        raw_budget = configured.get(intensity, DEFAULT_THINKING_BUDGETS[intensity])
        try:
            budget = int(raw_budget)
        except (TypeError, ValueError):
            budget = DEFAULT_THINKING_BUDGETS[intensity]

        # Anthropic-compatible thinking budgets count against max_tokens and
        # must leave room for the visible answer. Keep at least 1024 output
        # tokens when a cap is known.
        if max_tokens:
            if max_tokens > 2048:
                budget = min(budget, max_tokens - 1024)
            else:
                budget = min(budget, max(1, max_tokens // 2))
        return max(1, budget)

    def _map_reasoning_effort(self, thinking_intensity: Optional[str]) -> str:
        intensity = self._normalize_thinking_intensity(thinking_intensity)
        configured = self._policy_map("reasoning_effort") or self._policy_map("efforts")
        effort = configured.get(intensity, DEFAULT_REASONING_EFFORTS[intensity])
        effort_text = str(effort)
        return effort_text if effort_text in THINKING_INTENSITIES else DEFAULT_REASONING_EFFORTS[intensity]

    def _supports_openai_reasoning_effort(self, provider_name: str, litellm_provider: str) -> bool:
        provider_key = f"{provider_name} {litellm_provider}".lower()
        if "openai" not in provider_key:
            return False
        model = self.model_id.lower()
        return model.startswith(("o1", "o3", "o4", "gpt-5")) or "reasoning" in model

    def _litellm_thinking_kwargs(
        self,
        thinking_intensity: Optional[str],
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        provider_name, provider = self._get_provider()
        policy = self._thinking_policy()
        mode = str(policy.get("mode", "")).lower()

        if mode in {"off", "none", "disabled"}:
            return {}
        if mode in {"openai_reasoning_effort", "reasoning_effort"}:
            return {"reasoning_effort": self._map_reasoning_effort(thinking_intensity)}
        if mode in {"anthropic_budget", "thinking_budget"}:
            return {
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": self._map_thinking_budget(thinking_intensity, max_tokens),
                }
            }
        if self._supports_openai_reasoning_effort(provider_name, provider.litellm_provider):
            return {"reasoning_effort": self._map_reasoning_effort(thinking_intensity)}
        return {}

    @staticmethod
    def _thinking_controls_rejected(error_text: str) -> bool:
        lowered = error_text.lower()
        return any(
            marker in lowered
            for marker in (
                "reasoning_effort",
                "reasoning.effort",
                "budget_tokens",
                "unknown parameter: thinking",
                "unsupported parameter: thinking",
                "extra inputs are not permitted",
            )
        )

    def _map_generic_temperature(self, thinking_intensity: Optional[str], base: float) -> float:
        intensity = self._normalize_thinking_intensity(thinking_intensity)
        if intensity == "low":
            return max(0.1, min(base, 0.3))
        if intensity == "high":
            return min(1.0, max(base, 0.7))
        return base

    @staticmethod
    def _clean_messages_for_kimi(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cleaned: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            if role == "assistant":
                has_text = bool(str(message.get("content") or "").strip())
                has_tool_calls = bool(message.get("tool_calls"))
                has_reasoning = bool(str(message.get("reasoning_content") or "").strip())
                if not has_text and not has_tool_calls and not has_reasoning:
                    continue
            if "reasoning_content" in message:
                message = {k: v for k, v in message.items() if k != "reasoning_content"}
            cleaned.append(message)
        return cleaned

    @staticmethod
    async def _response_as_stream_events(response: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
        """Expose a full response through the same events as token streaming.

        Kimi's coding endpoint can accept streaming requests but sometimes
        buffers until completion or returns an empty SSE body.  In those cases
        we fall back to a normal completion and still need the UI to see the
        final text instead of only receiving a terminal done event.
        """
        message = response.get("choices", [{}])[0].get("message", {}) if response else {}
        reasoning = message.get("reasoning_content")
        if reasoning:
            yield {"type": "thinking_delta", "text": reasoning}
        content = message.get("content")
        if content:
            yield {"type": "text_delta", "text": content}
        yield {"type": "done", "response": response}

    def _kimi_prefers_openai_compatible(self) -> bool:
        _name, provider = self._get_provider()
        mode = (provider.litellm_provider or "").strip().lower()
        if mode in {"anthropic", "anthropic-messages", "anthropic_messages"}:
            return False
        if mode in {"openai", "openai-compatible", "openai_compatible"}:
            return True
        base = provider.base_url.rstrip("/")
        if base.endswith(("/v1/messages", "/messages")):
            return False
        return self._kimi_base_without_endpoint(base).endswith("/v1")

    @staticmethod
    def _kimi_base_without_endpoint(base_url: str) -> str:
        base = base_url.rstrip("/")
        for suffix in ("/chat/completions", "/v1/messages", "/messages", "/models"):
            if base.endswith(suffix):
                return base[: -len(suffix)].rstrip("/")
        return base

    def _kimi_openai_base_url(self) -> str:
        _name, provider = self._get_provider()
        base = self._kimi_base_without_endpoint(provider.base_url)
        return base if base.endswith("/v1") else f"{base}/v1"

    def _kimi_anthropic_base_url(self) -> str:
        _name, provider = self._get_provider()
        base = self._kimi_base_without_endpoint(provider.base_url)
        if base.endswith("/v1"):
            base = base[:-3].rstrip("/")
        return base

    def _build_kimi_openai_request(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> tuple[str, dict, dict]:
        """Build request for Kimi Code OpenAI-compatible /chat/completions."""
        _name, provider = self._get_provider()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {provider.api_key}",
            "User-Agent": "Kilo-Code/1.0",
        }
        payload: Dict[str, Any] = {
            "model": self.model_id,
            "messages": self._clean_messages_for_kimi(messages),
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        return self._kimi_openai_base_url(), headers, payload

    def _build_kimi_anthropic_request(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        max_tokens: Optional[int] = None,
        thinking_intensity: Optional[str] = None,
    ) -> tuple[str, dict, dict]:
        """Build (api_base, headers, payload) for Kimi Anthropic-compatible API."""
        _name, provider = self._get_provider()
        api_base = self._kimi_anthropic_base_url()
        headers = {
            "Content-Type": "application/json",
            "x-api-key": provider.api_key,
            "anthropic-version": "2023-06-01",
            "User-Agent": "Kilo-Code/1.0",
        }

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
                if content_blocks:
                    anthropic_messages.append({"role": "assistant", "content": content_blocks})
            elif role == "tool":
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
                continue
            else:
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
                    if anthropic_messages and anthropic_messages[-1].get("role") == "user":
                        existing = anthropic_messages[-1]["content"]
                        if isinstance(existing, list):
                            existing.extend(anthropic_content)
                        else:
                            anthropic_messages[-1]["content"] = [{"type": "text", "text": str(existing)}] + anthropic_content
                    else:
                        anthropic_messages.append({"role": "user", "content": anthropic_content})
                else:
                    if anthropic_messages and anthropic_messages[-1].get("role") == "user":
                        existing = anthropic_messages[-1]["content"]
                        if isinstance(existing, list):
                            existing.append({"type": "text", "text": str(content)})
                        else:
                            anthropic_messages[-1]["content"] = str(existing) + "\n" + str(content)
                    else:
                        anthropic_messages.append({"role": "user", "content": content})
            i += 1

        if anthropic_messages and anthropic_messages[0].get("role") != "user":
            anthropic_messages.insert(0, {"role": "user", "content": "(history truncated)"})
        output_max_tokens = max_tokens or 4096
        payload: Dict[str, Any] = {
            "model": self.model_id,
            "max_tokens": output_max_tokens,
            "messages": anthropic_messages,
        }
        if system_text:
            payload["system"] = system_text
        payload["thinking"] = {
            "type": "enabled",
            "budget_tokens": self._map_thinking_budget(thinking_intensity, output_max_tokens),
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

        return api_base, headers, payload

    @staticmethod
    def _parse_kimi_anthropic_response(data: dict) -> dict:
        """Parse Anthropic-format response content blocks into an OpenAI-format message dict."""
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
        }

    async def _call_kimi_anthropic(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        max_tokens: Optional[int] = None,
        thinking_intensity: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Kimi Code API 专用：使用 Anthropic 兼容端点获取 thinking 内容。"""
        api_base, headers, payload = self._build_kimi_anthropic_request(
            messages, tools, max_tokens, thinking_intensity,
        )

        async with httpx.AsyncClient(timeout=120) as client:
            for attempt in range(len(KIMI_RETRY_DELAYS_SECONDS) + 1):
                resp = await client.post(f"{api_base}/v1/messages", headers=headers, json=payload)
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

                if _is_retryable_provider_status(resp.status_code) and attempt < len(KIMI_RETRY_DELAYS_SECONDS):
                    resp_text = ""
                    try:
                        resp_text = (resp.text or "")[:2000]
                    except Exception:
                        pass
                    logger.warning(
                        "Kimi API transient failure, retrying: status=%s attempt=%s response_text=%s",
                        resp.status_code,
                        attempt + 1,
                        resp_text,
                    )
                    await asyncio.sleep(_retry_delay_seconds(resp, attempt))
                    continue

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
                        len(payload.get("messages", [])),
                        len(payload.get("tools", [])),
                        _safe_message_summary(payload.get("messages", [])),
                    )
                    raise httpx.HTTPStatusError(
                        _friendly_kimi_error(resp.status_code, resp_text2),
                        request=resp.request,
                        response=resp,
                    )
                data = resp.json()
                break

        result = self._parse_kimi_anthropic_response(data)
        result["model"] = f"kimi/{self.model_id}"
        result["usage"] = data.get("usage", {})
        return result

    async def _call_kimi_anthropic_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        max_tokens: Optional[int] = None,
        thinking_intensity: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Kimi Anthropic-compatible SSE streaming."""
        api_base, headers, payload = self._build_kimi_anthropic_request(
            messages, tools, max_tokens, thinking_intensity,
        )
        payload["stream"] = True

        async with httpx.AsyncClient(timeout=180) as client:
            for attempt in range(len(KIMI_RETRY_DELAYS_SECONDS) + 1):
                async with client.stream("POST", f"{api_base}/v1/messages", headers=headers, json=payload) as resp:
                    if resp.status_code == 400 and tools:
                        body = ""
                        try:
                            body = (await resp.aread()).decode("utf-8", errors="ignore")[:2000]
                        except Exception:
                            pass
                        if "thinking" in body.lower():
                            logger.info("Kimi stream rejected thinking+tools, retrying without thinking")
                            payload.pop("thinking", None)
                            payload.pop("stream", None)
                            # Fall back to non-stream for the retry
                            async with httpx.AsyncClient(timeout=120) as retry_client:
                                retry_resp = await retry_client.post(
                                    f"{api_base}/v1/messages", headers=headers, json=payload,
                                )
                                try:
                                    retry_resp.raise_for_status()
                                except httpx.HTTPStatusError:
                                    retry_body = ""
                                    try:
                                        retry_body = (retry_resp.text or "")[:2000]
                                    except Exception:
                                        pass
                                    raise httpx.HTTPStatusError(
                                        _friendly_kimi_error(retry_resp.status_code, retry_body),
                                        request=retry_resp.request,
                                        response=retry_resp,
                                    )
                                data = retry_resp.json()
                            result = self._parse_kimi_anthropic_response(data)
                            result["usage"] = data.get("usage", {})
                            async for event in self._response_as_stream_events(result):
                                yield event
                            return

                    if resp.status_code != 200:
                        body = ""
                        try:
                            body = (await resp.aread()).decode("utf-8", errors="ignore")[:2000]
                        except Exception:
                            pass
                        if _is_retryable_provider_status(resp.status_code) and attempt < len(KIMI_RETRY_DELAYS_SECONDS):
                            logger.warning(
                                "Kimi stream transient failure, retrying: status=%s attempt=%s response_text=%s",
                                resp.status_code,
                                attempt + 1,
                                body,
                            )
                            await asyncio.sleep(_retry_delay_seconds(resp, attempt))
                            continue
                        raise httpx.HTTPStatusError(
                            _friendly_kimi_error(resp.status_code, body),
                            request=resp.request,
                            response=resp,
                        )

                    # Parse SSE stream
                    thinking_text = ""
                    text_content = ""
                    tool_use_blocks: dict[int, dict] = {}  # index -> {id, name, input_json}

                    line_iter = resp.aiter_lines().__aiter__()
                    seen_sse_data = False
                    while True:
                        try:
                            line = await asyncio.wait_for(
                                line_iter.__anext__(),
                                timeout=KIMI_STREAM_IDLE_TIMEOUT_SECONDS
                                if seen_sse_data
                                else KIMI_STREAM_FIRST_EVENT_TIMEOUT_SECONDS,
                            )
                        except StopAsyncIteration:
                            break
                        except asyncio.TimeoutError:
                            if not seen_sse_data:
                                logger.warning("Kimi stream produced no first event; falling back to non-stream")
                                fallback = await self._call_kimi_anthropic(
                                    messages=messages,
                                    tools=tools,
                                    max_tokens=max_tokens,
                                    thinking_intensity=thinking_intensity,
                                )
                                async for event in self._response_as_stream_events(fallback):
                                    yield event
                                return
                            raise httpx.ReadTimeout(
                                "Kimi stream stalled while waiting for the next event",
                                request=resp.request,
                            )

                        if not line or not line.startswith("data: "):
                            continue
                        seen_sse_data = True
                        data_str = line[len("data: "):]
                        try:
                            event = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        etype = event.get("type", "")
                        if etype == "content_block_start":
                            block = event.get("content_block", {})
                            idx = event.get("index", 0)
                            if block.get("type") == "tool_use":
                                tool_use_blocks[idx] = {
                                    "id": block.get("id", ""),
                                    "name": block.get("name", ""),
                                    "input_json": "",
                                }
                        elif etype == "content_block_delta":
                            delta = event.get("delta", {})
                            dtype = delta.get("type", "")
                            if dtype == "thinking_delta":
                                token = delta.get("thinking") or delta.get("text") or delta.get("content") or ""
                                thinking_text += token
                                yield {"type": "thinking_delta", "text": token}
                            elif dtype == "text_delta":
                                token = delta.get("text") or delta.get("content") or ""
                                text_content += token
                                yield {"type": "text_delta", "text": token}
                            elif dtype == "input_json_delta":
                                idx = event.get("index", 0)
                                if idx in tool_use_blocks:
                                    tool_use_blocks[idx]["input_json"] += delta.get("partial_json", "")
                        elif etype == "content_block_stop":
                            pass
                        elif etype == "message_delta":
                            pass
                        elif etype == "message_stop":
                            break

                    # Build final tool_calls from accumulated blocks
                    tool_calls = []
                    for idx in sorted(tool_use_blocks.keys()):
                        tb = tool_use_blocks[idx]
                        try:
                            args = json.loads(tb["input_json"]) if tb["input_json"].strip() else {}
                        except json.JSONDecodeError:
                            args = {}
                        tool_calls.append({
                            "id": tb["id"],
                            "type": "function",
                            "function": {
                                "name": tb["name"],
                                "arguments": json.dumps(args),
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

                    if _is_empty_openai_message(openai_msg):
                        logger.warning("Kimi stream completed with an empty message; falling back to non-stream")
                        fallback = await self._call_kimi_anthropic(
                            messages=messages,
                            tools=tools,
                            max_tokens=max_tokens,
                            thinking_intensity=thinking_intensity,
                        )
                        async for event in self._response_as_stream_events(fallback):
                            yield event
                        return

                    response = {
                        "choices": [{
                            "index": 0,
                            "message": openai_msg,
                            "finish_reason": "tool_calls" if tool_calls else "stop",
                        }],
                    }
                    yield {"type": "done", "response": response}
                    return

    async def _call_kimi_openai(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Kimi Code OpenAI-compatible non-streaming chat completion."""
        api_base, headers, payload = self._build_kimi_openai_request(
            messages, tools, temperature, max_tokens,
        )

        async with httpx.AsyncClient(timeout=120) as client:
            for attempt in range(len(KIMI_RETRY_DELAYS_SECONDS) + 1):
                resp = await client.post(f"{api_base}/chat/completions", headers=headers, json=payload)
                if _is_retryable_provider_status(resp.status_code) and attempt < len(KIMI_RETRY_DELAYS_SECONDS):
                    body = ""
                    try:
                        body = (resp.text or "")[:2000]
                    except Exception:
                        pass
                    logger.warning(
                        "Kimi OpenAI-compatible request transient failure, retrying: status=%s attempt=%s response_text=%s",
                        resp.status_code,
                        attempt + 1,
                        body,
                    )
                    await asyncio.sleep(_retry_delay_seconds(resp, attempt))
                    continue
                break
            if resp.status_code >= 400:
                body = ""
                try:
                    body = (resp.text or "")[:2000]
                except Exception:
                    pass
                logger.warning(
                    "Kimi OpenAI-compatible request failed: status=%s response_text=%s message_count=%s tool_count=%s message_summary=%s",
                    resp.status_code,
                    body,
                    len(payload.get("messages", [])),
                    len(payload.get("tools", [])),
                    _safe_message_summary(payload.get("messages", [])),
                )
                raise httpx.HTTPStatusError(
                    _friendly_kimi_error(resp.status_code, body),
                    request=resp.request,
                    response=resp,
                )
            data = resp.json()
        data["model"] = data.get("model") or f"kimi/{self.model_id}"
        return data

    async def _call_kimi_openai_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Kimi Code OpenAI-compatible SSE streaming."""
        api_base, headers, payload = self._build_kimi_openai_request(
            messages, tools, temperature, max_tokens,
        )
        payload["stream"] = True

        async with httpx.AsyncClient(timeout=180) as client:
            for attempt in range(len(KIMI_RETRY_DELAYS_SECONDS) + 1):
                async with client.stream("POST", f"{api_base}/chat/completions", headers=headers, json=payload) as resp:
                    if resp.status_code != 200:
                        body = ""
                        try:
                            body = (await resp.aread()).decode("utf-8", errors="ignore")[:2000]
                        except Exception:
                            pass
                        if _is_retryable_provider_status(resp.status_code) and attempt < len(KIMI_RETRY_DELAYS_SECONDS):
                            logger.warning(
                                "Kimi OpenAI-compatible stream transient failure, retrying: status=%s attempt=%s response_text=%s",
                                resp.status_code,
                                attempt + 1,
                                body,
                            )
                            await asyncio.sleep(_retry_delay_seconds(resp, attempt))
                            continue
                        logger.warning(
                            "Kimi OpenAI-compatible stream failed: status=%s response_text=%s",
                            resp.status_code,
                            body,
                        )
                        raise httpx.HTTPStatusError(
                            _friendly_kimi_error(resp.status_code, body),
                            request=resp.request,
                            response=resp,
                        )

                    reasoning_text = ""
                    content_text = ""
                    tool_calls_by_idx: dict[int, dict] = {}
                    seen_sse_data = False
                    line_iter = resp.aiter_lines().__aiter__()
                    while True:
                        try:
                            line = await asyncio.wait_for(
                                line_iter.__anext__(),
                                timeout=KIMI_STREAM_IDLE_TIMEOUT_SECONDS
                                if seen_sse_data
                                else KIMI_STREAM_FIRST_EVENT_TIMEOUT_SECONDS,
                            )
                        except StopAsyncIteration:
                            break
                        except asyncio.TimeoutError:
                            if not seen_sse_data:
                                logger.warning("Kimi OpenAI-compatible stream produced no first event; falling back to non-stream")
                                fallback = await self._call_kimi_openai(
                                    messages=messages,
                                    tools=tools,
                                    temperature=temperature,
                                    max_tokens=max_tokens,
                                )
                                async for event in self._response_as_stream_events(fallback):
                                    yield event
                                return
                            raise httpx.ReadTimeout(
                                "Kimi OpenAI-compatible stream stalled while waiting for the next event",
                                request=resp.request,
                            )

                        if not line:
                            continue
                        if line == "data: [DONE]":
                            break
                        if not line.startswith("data: "):
                            continue
                        seen_sse_data = True
                        data_str = line[len("data: "):]
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})

                        rc = delta.get("reasoning_content")
                        if rc:
                            reasoning_text += rc
                            yield {"type": "thinking_delta", "text": rc}

                        content = delta.get("content")
                        if content:
                            content_text += content
                            yield {"type": "text_delta", "text": content}

                        for tool_call in delta.get("tool_calls") or []:
                            idx = tool_call.get("index", 0)
                            if idx not in tool_calls_by_idx:
                                tool_calls_by_idx[idx] = {
                                    "id": tool_call.get("id", ""),
                                    "name": tool_call.get("function", {}).get("name", ""),
                                    "arguments": "",
                                }
                            func = tool_call.get("function", {})
                            if tool_call.get("id"):
                                tool_calls_by_idx[idx]["id"] = tool_call["id"]
                            if func.get("name"):
                                tool_calls_by_idx[idx]["name"] = func["name"]
                            tool_calls_by_idx[idx]["arguments"] += func.get("arguments", "")

                    tool_calls = []
                    for idx in sorted(tool_calls_by_idx.keys()):
                        tb = tool_calls_by_idx[idx]
                        try:
                            args = json.loads(tb["arguments"]) if tb["arguments"].strip() else {}
                        except json.JSONDecodeError:
                            args = {}
                        tool_calls.append({
                            "id": tb["id"],
                            "type": "function",
                            "function": {
                                "name": tb["name"],
                                "arguments": json.dumps(args),
                            },
                        })

                    openai_msg: Dict[str, Any] = {
                        "role": "assistant",
                        "content": content_text,
                    }
                    if reasoning_text:
                        openai_msg["reasoning_content"] = reasoning_text
                    if tool_calls:
                        openai_msg["tool_calls"] = tool_calls

                    if _is_empty_openai_message(openai_msg):
                        logger.warning("Kimi OpenAI-compatible stream completed with an empty message; falling back to non-stream")
                        fallback = await self._call_kimi_openai(
                            messages=messages,
                            tools=tools,
                            temperature=temperature,
                            max_tokens=max_tokens,
                        )
                        async for event in self._response_as_stream_events(fallback):
                            yield event
                        return

                    yield {
                        "type": "done",
                        "response": {
                            "choices": [{
                                "index": 0,
                                "message": openai_msg,
                                "finish_reason": "tool_calls" if tool_calls else "stop",
                            }],
                        },
                    }
                    return

    def _is_deepseek(self) -> bool:
        provider_name, provider = self._get_provider()
        return provider_name == "deepseek" or provider.litellm_provider == "deepseek"

    def _build_deepseek_request(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        thinking_intensity: Optional[str] = None,
    ) -> tuple[str, dict, dict]:
        """Build (api_base, headers, payload) for DeepSeek API."""
        _, provider = self._get_provider()
        api_base = provider.base_url.rstrip("/")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {provider.api_key}",
        }
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
        return api_base, headers, payload

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
        api_base, headers, payload = self._build_deepseek_request(
            messages, tools, temperature, max_tokens, thinking_intensity,
        )

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

    async def _call_deepseek_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        thinking_intensity: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """DeepSeek OpenAI-compatible SSE streaming."""
        api_base, headers, payload = self._build_deepseek_request(
            messages, tools, temperature, max_tokens, thinking_intensity,
        )
        payload["stream"] = True

        async with httpx.AsyncClient(timeout=180) as client:
            async with client.stream("POST", f"{api_base}/chat/completions", headers=headers, json=payload) as resp:
                if resp.status_code != 200:
                    body = ""
                    try:
                        body = (await resp.aread()).decode("utf-8", errors="ignore")[:2000]
                    except Exception:
                        pass
                    logger.warning(
                        "DeepSeek stream failed: status=%s response_text=%s",
                        resp.status_code,
                        body,
                    )
                    raise httpx.HTTPStatusError(
                        f"DeepSeek stream failed: {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )

                reasoning_text = ""
                content_text = ""
                tool_calls_by_idx: dict[int, dict] = {}

                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line == "data: [DONE]":
                        break
                    if not line.startswith("data: "):
                        continue
                    data_str = line[len("data: "):]
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})

                    rc = delta.get("reasoning_content")
                    if rc:
                        reasoning_text += rc
                        yield {"type": "thinking_delta", "text": rc}

                    c = delta.get("content")
                    if c:
                        content_text += c
                        yield {"type": "text_delta", "text": c}

                    tc_list = delta.get("tool_calls")
                    if tc_list:
                        for tc in tc_list:
                            idx = tc.get("index", 0)
                            if idx not in tool_calls_by_idx:
                                tool_calls_by_idx[idx] = {
                                    "id": tc.get("id", ""),
                                    "name": tc.get("function", {}).get("name", ""),
                                    "arguments": "",
                                }
                            func = tc.get("function", {})
                            if func.get("id"):
                                tool_calls_by_idx[idx]["id"] = func["id"]
                            if func.get("name"):
                                tool_calls_by_idx[idx]["name"] = func["name"]
                            tool_calls_by_idx[idx]["arguments"] += func.get("arguments", "")

                # Build final tool_calls
                tool_calls = []
                for idx in sorted(tool_calls_by_idx.keys()):
                    tb = tool_calls_by_idx[idx]
                    try:
                        args = json.loads(tb["arguments"]) if tb["arguments"].strip() else {}
                    except json.JSONDecodeError:
                        args = {}
                    tool_calls.append({
                        "id": tb["id"],
                        "type": "function",
                        "function": {
                            "name": tb["name"],
                            "arguments": json.dumps(args),
                        },
                    })

                openai_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": content_text,
                }
                if reasoning_text:
                    openai_msg["reasoning_content"] = reasoning_text
                if tool_calls:
                    openai_msg["tool_calls"] = tool_calls

                response = {
                    "choices": [{
                        "index": 0,
                        "message": openai_msg,
                        "finish_reason": "tool_calls" if tool_calls else "stop",
                    }],
                }
                yield {"type": "done", "response": response}

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
        thinking_kwargs = self._litellm_thinking_kwargs(thinking_intensity, max_tokens)
        base_kwargs = {
            "model": f"{litellm_provider}/{self.model_id}",
            "messages": messages,
            "tools": tools,
            "temperature": self._map_generic_temperature(thinking_intensity, temperature),
            "max_tokens": max_tokens,
            "api_base": api_base if api_base else None,
            "api_key": provider.api_key if provider.api_key else None,
            "stream": stream,
        }
        if "reasoning_effort" in thinking_kwargs:
            base_kwargs.pop("temperature", None)

        try:
            return await acompletion(**base_kwargs, **thinking_kwargs)
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
                return await acompletion(**{**base_kwargs, "messages": stripped}, **thinking_kwargs)
            if thinking_kwargs and self._thinking_controls_rejected(error_text):
                logger.warning("Provider rejected native thinking controls, retrying without them")
                return await acompletion(**base_kwargs)
            raise

    async def _call_litellm_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        thinking_intensity: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream via LiteLLM, yielding progressive deltas."""
        provider_name, provider = self._get_provider()
        litellm_provider = provider.litellm_provider or ("openai" if provider_name == "local" else provider_name)
        api_base = provider.base_url
        thinking_kwargs = self._litellm_thinking_kwargs(thinking_intensity, max_tokens)
        base_kwargs = {
            "model": f"{litellm_provider}/{self.model_id}",
            "messages": messages,
            "tools": tools,
            "temperature": self._map_generic_temperature(thinking_intensity, temperature),
            "max_tokens": max_tokens,
            "api_base": api_base if api_base else None,
            "api_key": provider.api_key if provider.api_key else None,
            "stream": True,
        }
        if "reasoning_effort" in thinking_kwargs:
            base_kwargs.pop("temperature", None)

        reasoning_text = ""
        content_text = ""
        tool_call_chunks: dict[int, dict] = {}

        try:
            stream = await acompletion(**base_kwargs, **thinking_kwargs)
        except BadRequestError as e:
            error_text = str(e).lower()
            if "reasoning_content" in error_text and messages:
                if "must be passed back" in error_text:
                    logger.warning(
                        "reasoning_content required but missing — LiteLLM dropped it; "
                        "retrying via direct DeepSeek stream"
                    )
                    async for event in self._call_deepseek_stream(
                        messages=messages, tools=tools, temperature=temperature,
                        max_tokens=max_tokens, thinking_intensity=thinking_intensity,
                    ):
                        yield event
                    return
                logger.warning(
                    "reasoning_content rejected by upstream, stripping and retrying stream"
                )
                stripped = []
                for msg in messages:
                    if msg.get("role") == "assistant" and "reasoning_content" in msg:
                        msg = {k: v for k, v in msg.items() if k != "reasoning_content"}
                    stripped.append(msg)
                stream = await acompletion(**{**base_kwargs, "messages": stripped}, **thinking_kwargs)
            elif thinking_kwargs and self._thinking_controls_rejected(error_text):
                logger.warning("Provider rejected native thinking controls, retrying stream without them")
                stream = await acompletion(**base_kwargs)
            else:
                raise

        async for chunk in stream:
            choices = chunk.choices if hasattr(chunk, "choices") else []
            if not choices:
                continue
            delta = choices[0].delta if hasattr(choices[0], "delta") else None
            if delta is None:
                continue

            rc = getattr(delta, "reasoning_content", None)
            if rc:
                reasoning_text += rc
                yield {"type": "thinking_delta", "text": rc}

            c = getattr(delta, "content", None)
            if c:
                content_text += c
                yield {"type": "text_delta", "text": c}

            tc_list = getattr(delta, "tool_calls", None)
            if tc_list:
                for tc in tc_list:
                    idx = getattr(tc, "index", 0)
                    if idx not in tool_call_chunks:
                        tool_call_chunks[idx] = {
                            "id": getattr(tc, "id", "") or "",
                            "name": (getattr(tc, "function", None) or {}).get("name", "") if hasattr(tc, "function") else "",
                            "arguments": "",
                        }
                    func = getattr(tc, "function", None)
                    if func is not None:
                        if getattr(func, "id", None):
                            tool_call_chunks[idx]["id"] = func.id
                        if getattr(func, "name", None):
                            tool_call_chunks[idx]["name"] = func.name
                        tool_call_chunks[idx]["arguments"] += getattr(func, "arguments", "") or ""

        # Build final tool_calls
        tool_calls = []
        for idx in sorted(tool_call_chunks.keys()):
            tb = tool_call_chunks[idx]
            try:
                args = json.loads(tb["arguments"]) if tb["arguments"].strip() else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({
                "id": tb["id"],
                "type": "function",
                "function": {
                    "name": tb["name"],
                    "arguments": json.dumps(args),
                },
            })

        openai_msg: Dict[str, Any] = {
            "role": "assistant",
            "content": content_text,
        }
        if reasoning_text:
            openai_msg["reasoning_content"] = reasoning_text
        if tool_calls:
            openai_msg["tool_calls"] = tool_calls

        response = {
            "choices": [{
                "index": 0,
                "message": openai_msg,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }],
        }
        yield {"type": "done", "response": response}

    async def chat_completion_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        thinking_intensity: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Unified streaming completion. Yields delta events then a 'done' event with full response."""
        provider_name = self._get_provider()[0]
        if provider_name == "kimi":
            if self._kimi_prefers_openai_compatible():
                async for event in self._call_kimi_openai_stream(
                    messages=messages, tools=tools, temperature=temperature, max_tokens=max_tokens,
                ):
                    yield event
            else:
                async for event in self._call_kimi_anthropic_stream(
                    messages=messages, tools=tools, max_tokens=max_tokens, thinking_intensity=thinking_intensity,
                ):
                    yield event
        elif self._is_deepseek():
            async for event in self._call_deepseek_stream(
                messages=messages, tools=tools, temperature=temperature,
                max_tokens=max_tokens, thinking_intensity=thinking_intensity,
            ):
                yield event
        else:
            async for event in self._call_litellm_stream(
                messages=messages, tools=tools, temperature=temperature,
                max_tokens=max_tokens, thinking_intensity=thinking_intensity,
            ):
                yield event

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
            if self._kimi_prefers_openai_compatible():
                response = await self._call_kimi_openai(
                    messages=messages, tools=tools, temperature=temperature, max_tokens=max_tokens,
                )
            else:
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
            if self._kimi_prefers_openai_compatible():
                return await self._call_kimi_openai(
                    messages=messages, tools=tools, temperature=temperature, max_tokens=max_tokens,
                )
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
