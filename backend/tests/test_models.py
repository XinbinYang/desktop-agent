import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.models import ModelRouter


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
