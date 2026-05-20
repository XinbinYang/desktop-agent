import pytest
import httpx
import json
from unittest.mock import patch, MagicMock, AsyncMock
from app.models import ModelRouter, _safe_message_summary


class TestModelRouter:
    @pytest.fixture
    def router(self, monkeypatch, tmp_path):
        config_yaml = tmp_path / "models.yaml"
        config_yaml.write_text("""
providers:
  openai:
    base_url: https://api.openai.com/v1
    api_key: test-key
    models:
      - id: gpt-4o
        name: GPT-4o
        context: 128000
        vision: true
settings:
  default_model: gpt-4o
  default_provider: openai
""")
        monkeypatch.setattr("app.config.CONFIG_PATH", config_yaml)
        from app import config
        config._config = None
        return ModelRouter("gpt-4o")

    @pytest.mark.asyncio
    async def test_chat_completion_non_stream(self, router):
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "choices": [{"message": {"content": "Hi"}}]
        }

        with patch("app.models.acompletion", new_callable=AsyncMock, return_value=mock_response):
            result = await router.chat_completion_non_stream(
                messages=[{"role": "user", "content": "hello"}]
            )
            assert "choices" in result

    @pytest.mark.asyncio
    async def test_chat_completion_stream(self, router):
        mock_chunk = MagicMock()
        mock_chunk.model_dump.return_value = {"choices": [{"delta": {"content": "Hi"}}]}

        async def mock_async_generator():
            yield mock_chunk

        with patch("app.models.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = mock_async_generator()
            chunks = []
            async for chunk in router.chat_completion(
                messages=[{"role": "user", "content": "hello"}],
                stream=True
            ):
                chunks.append(chunk)
            assert len(chunks) > 0

    def test_build_vision_message(self, router):
        msg = router.build_vision_message("Describe this", "base64data")
        assert msg["role"] == "user"
        assert isinstance(msg["content"], list)
        assert msg["content"][0]["type"] == "text"
        assert msg["content"][1]["type"] == "image_url"
        assert "base64data" in msg["content"][1]["image_url"]["url"]

    def test_encode_image_to_base64(self, tmp_path):
        img_file = tmp_path / "test.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"fake_png_data")
        b64 = ModelRouter.encode_image_to_base64(str(img_file))
        assert isinstance(b64, str)
        assert len(b64) > 0

    def test_unknown_model_raises(self, monkeypatch, tmp_path):
        config_yaml = tmp_path / "models.yaml"
        config_yaml.write_text("""
providers:
  p:
    base_url: http://x
    api_key: k
    models:
      - id: m
        name: M
        context: 1
settings:
  default_model: m
  default_provider: p
""")
        monkeypatch.setattr("app.config.CONFIG_PATH", config_yaml)
        from app import config
        config._config = None

        with pytest.raises(ValueError, match="Unknown model"):
            ModelRouter("nonexistent-model")

    def test_safe_message_summary_does_not_include_content(self):
        summary = _safe_message_summary([
            {"role": "user", "content": "secret prompt"},
            {"role": "assistant", "content": [{"type": "text", "text": "secret answer"}]},
            {"role": "tool", "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "secret result"}]},
        ])

        rendered = repr(summary)
        assert "secret prompt" not in rendered
        assert "secret answer" not in rendered
        assert "secret result" not in rendered
        assert "length" in rendered

    def test_thinking_intensity_maps_budget_and_temperature(self, router):
        assert router._map_thinking_budget("low") == 2048
        assert router._map_thinking_budget("medium") == 4096
        assert router._map_thinking_budget("high") == 6144
        assert router._map_thinking_budget("high", max_tokens=8192) == 6144
        assert router._map_thinking_budget("high", max_tokens=4096) == 3072
        assert router._map_generic_temperature("low", 0.5) <= 0.5
        assert router._map_generic_temperature("high", 0.5) >= 0.5

    def test_kimi_thinking_budget_leaves_answer_tokens(self, monkeypatch, tmp_path):
        config_yaml = tmp_path / "models.yaml"
        config_yaml.write_text("""
providers:
  kimi:
    base_url: https://api.kimi.com/coding/v1
    api_key: test-key
    models:
      - id: kimi-for-coding
        name: Kimi
        context: 256000
        vision: true
settings:
  default_model: kimi-for-coding
  default_provider: kimi
""")
        monkeypatch.setattr("app.config.CONFIG_PATH", config_yaml)
        from app import config
        config._config = None

        router = ModelRouter("kimi-for-coding")
        _, _, payload = router._build_kimi_anthropic_request(
            [{"role": "user", "content": "hello"}],
            max_tokens=8192,
            thinking_intensity="high",
        )

        assert payload["thinking"]["budget_tokens"] == 6144
        assert payload["thinking"]["budget_tokens"] < payload["max_tokens"]

    @pytest.mark.asyncio
    async def test_openai_reasoning_model_uses_reasoning_effort(self, monkeypatch, tmp_path):
        config_yaml = tmp_path / "models.yaml"
        config_yaml.write_text("""
providers:
  openai:
    base_url: https://api.openai.com/v1
    api_key: test-key
    models:
      - id: o3-mini
        name: o3 mini
        context: 200000
        vision: false
settings:
  default_model: o3-mini
  default_provider: openai
""")
        monkeypatch.setattr("app.config.CONFIG_PATH", config_yaml)
        from app import config
        config._config = None

        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "choices": [{"message": {"content": "Hi"}}]
        }
        mock_response.choices[0].message.reasoning_content = None

        router = ModelRouter("o3-mini")
        with patch("app.models.acompletion", new_callable=AsyncMock, return_value=mock_response) as mock_acompletion:
            await router.chat_completion_non_stream(
                messages=[{"role": "user", "content": "hello"}],
                thinking_intensity="high",
            )

        kwargs = mock_acompletion.await_args.kwargs
        assert kwargs["reasoning_effort"] == "high"
        assert "temperature" not in kwargs

    def test_kimi_coding_v1_prefers_openai_compatible_route(self, monkeypatch, tmp_path):
        config_yaml = tmp_path / "models.yaml"
        config_yaml.write_text("""
providers:
  kimi:
    base_url: https://api.kimi.com/coding/v1
    api_key: test-key
    models:
      - id: kimi-for-coding
        name: Kimi Coding
        context: 256000
        vision: true
settings:
  default_model: kimi-for-coding
  default_provider: kimi
""")
        monkeypatch.setattr("app.config.CONFIG_PATH", config_yaml)
        from app import config
        config._config = None

        router = ModelRouter("kimi-for-coding")

        assert router._kimi_prefers_openai_compatible() is True
        assert router._kimi_openai_base_url() == "https://api.kimi.com/coding/v1"
        assert router._kimi_anthropic_base_url() == "https://api.kimi.com/coding"

    def test_kimi_messages_endpoint_prefers_anthropic_route(self, monkeypatch, tmp_path):
        config_yaml = tmp_path / "models.yaml"
        config_yaml.write_text("""
providers:
  kimi:
    base_url: https://api.kimi.com/coding/v1/messages
    api_key: test-key
    models:
      - id: kimi-for-coding
        name: Kimi Coding
        context: 256000
        vision: true
settings:
  default_model: kimi-for-coding
  default_provider: kimi
""")
        monkeypatch.setattr("app.config.CONFIG_PATH", config_yaml)
        from app import config
        config._config = None

        router = ModelRouter("kimi-for-coding")

        assert router._kimi_prefers_openai_compatible() is False
        assert router._kimi_openai_base_url() == "https://api.kimi.com/coding/v1"
        assert router._kimi_anthropic_base_url() == "https://api.kimi.com/coding"

    def test_kimi_openai_request_drops_empty_assistant_history(self, monkeypatch, tmp_path):
        config_yaml = tmp_path / "models.yaml"
        config_yaml.write_text("""
providers:
  kimi:
    base_url: https://api.kimi.com/coding/v1
    api_key: test-key
    models:
      - id: kimi-for-coding
        name: Kimi Coding
        context: 256000
        vision: true
settings:
  default_model: kimi-for-coding
  default_provider: kimi
""")
        monkeypatch.setattr("app.config.CONFIG_PATH", config_yaml)
        from app import config
        config._config = None
        router = ModelRouter("kimi-for-coding")

        _, _, payload = router._build_kimi_openai_request([
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "continue"},
        ])

        assert payload["messages"] == [
            {"role": "user", "content": "hello"},
            {"role": "user", "content": "continue"},
        ]

    def test_kimi_openai_request_preserves_reasoning_content(self, monkeypatch, tmp_path):
        config_yaml = tmp_path / "models.yaml"
        config_yaml.write_text("""
providers:
  kimi:
    base_url: https://api.kimi.com/coding/v1
    api_key: test-key
    models:
      - id: kimi-for-coding
        name: Kimi Coding
        context: 256000
        vision: true
settings:
  default_model: kimi-for-coding
  default_provider: kimi
""")
        monkeypatch.setattr("app.config.CONFIG_PATH", config_yaml)
        from app import config
        config._config = None
        router = ModelRouter("kimi-for-coding")

        _, _, payload = router._build_kimi_openai_request([
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "I need a file write.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "file_write", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "name": "file_write", "content": "ok"},
        ])

        assert payload["messages"][0]["reasoning_content"] == "I need a file write."

    def test_deepseek_request_converts_image_url_history_to_text(self, monkeypatch, tmp_path):
        config_yaml = tmp_path / "models.yaml"
        config_yaml.write_text("""
providers:
  deepseek:
    base_url: https://api.deepseek.com
    api_key: test-key
    litellm_provider: deepseek
    models:
      - id: deepseek-chat
        name: DeepSeek Chat
        context: 65536
        vision: false
settings:
  default_model: deepseek-chat
  default_provider: deepseek
""")
        monkeypatch.setattr("app.config.CONFIG_PATH", config_yaml)
        from app import config
        config._config = None
        router = ModelRouter("deepseek-chat")

        original_messages = [
            {"role": "system", "content": "system prompt"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe this"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,secretbase64"}},
                ],
            },
            {"role": "assistant", "content": "ok", "reasoning_content": "reasoning"},
        ]

        _, _, payload = router._build_deepseek_request(original_messages)

        assert payload["messages"][1]["content"] == (
            "describe this\n\n"
            "[image omitted: DeepSeek does not accept image content]"
        )
        rendered = json.dumps(payload["messages"])
        assert "image_url" not in rendered
        assert "secretbase64" not in rendered
        assert payload["messages"][2]["reasoning_content"] == "reasoning"
        assert original_messages[1]["content"][1]["image_url"]["url"].endswith("secretbase64")

    def test_kimi_anthropic_request_drops_empty_assistant_history(self, monkeypatch, tmp_path):
        config_yaml = tmp_path / "models.yaml"
        config_yaml.write_text("""
providers:
  kimi:
    base_url: https://api.kimi.com/coding
    api_key: test-key
    models:
      - id: kimi-for-coding
        name: Kimi Coding
        context: 256000
        vision: true
settings:
  default_model: kimi-for-coding
  default_provider: kimi
""")
        monkeypatch.setattr("app.config.CONFIG_PATH", config_yaml)
        from app import config
        config._config = None
        router = ModelRouter("kimi-for-coding")

        _, _, payload = router._build_kimi_anthropic_request([
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "continue"},
        ])

        assert payload["messages"] == [
            {"role": "user", "content": "hello\ncontinue"},
        ]

    def test_kimi_anthropic_request_preserves_reasoning_content(self, monkeypatch, tmp_path):
        config_yaml = tmp_path / "models.yaml"
        config_yaml.write_text("""
providers:
  kimi:
    base_url: https://api.kimi.com/coding
    api_key: test-key
    models:
      - id: kimi-for-coding
        name: Kimi Coding
        context: 256000
        vision: true
settings:
  default_model: kimi-for-coding
  default_provider: kimi
""")
        monkeypatch.setattr("app.config.CONFIG_PATH", config_yaml)
        from app import config
        config._config = None
        router = ModelRouter("kimi-for-coding")

        _, _, payload = router._build_kimi_anthropic_request([
            {"role": "user", "content": "write a file"},
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "I need a file write.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "file_write", "arguments": "{\"path\":\"x\"}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "name": "file_write", "content": "ok"},
        ])

        assert payload["messages"][1]["reasoning_content"] == "I need a file write."

    @pytest.mark.asyncio
    async def test_kimi_post_retries_transport_disconnect(self, router):
        class FakeClient:
            def __init__(self):
                self.calls = 0

            async def post(self, url, headers=None, json=None):
                self.calls += 1
                if self.calls == 1:
                    raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
                request = httpx.Request("POST", url)
                return httpx.Response(200, json={"ok": True}, request=request)

        client = FakeClient()
        response = await router._kimi_post_json_with_retries(
            client,
            "https://api.kimi.com/coding/v1/messages",
            {},
            {"messages": [{"role": "user", "content": "hello"}]},
            "test",
        )

        assert response.status_code == 200
        assert client.calls == 2

    @pytest.mark.asyncio
    async def test_kimi_stream_uses_non_stream_call(self, monkeypatch, tmp_path):
        """Kimi's coding endpoint does not deliver usable incremental SSE on
        either protocol, so chat_completion_stream must use a single non-stream
        call replayed as events — no streaming attempt (which would only add a
        wasted upstream request before the same fallback).
        """
        config_yaml = tmp_path / "models.yaml"
        config_yaml.write_text("""
providers:
  kimi:
    base_url: https://api.kimi.com/coding/v1
    api_key: test-key
    models:
      - id: kimi-for-coding
        name: Kimi Coding
        context: 256000
        vision: true
settings:
  default_model: kimi-for-coding
  default_provider: kimi
""")
        monkeypatch.setattr("app.config.CONFIG_PATH", config_yaml)
        from app import config
        config._config = None
        router = ModelRouter("kimi-for-coding")

        async def openai_call(*args, **kwargs):
            return {"choices": [{"message": {"content": "ok"}}]}

        anthropic_stream_mock = MagicMock()
        openai_stream_mock = MagicMock()

        with (
            patch.object(router, "_call_kimi_openai", openai_call),
            patch.object(router, "_call_kimi_anthropic", new_callable=AsyncMock),
            patch.object(router, "_call_kimi_anthropic_stream", anthropic_stream_mock),
            patch.object(router, "_call_kimi_openai_stream", openai_stream_mock),
        ):
            events = []
            async for event in router.chat_completion_stream(messages=[{"role": "user", "content": "hi"}]):
                events.append(event)

        # The non-stream call is replayed as events; neither streaming helper
        # is invoked (no wasted upstream request / 429 amplification).
        assert events[-1]["response"]["choices"][0]["message"]["content"] == "ok"
        assert any(event["type"] == "text_delta" and event["text"] == "ok" for event in events)
        anthropic_stream_mock.assert_not_called()
        openai_stream_mock.assert_not_called()
