import pytest
import os
from unittest.mock import MagicMock, patch
from app.transcribe import _transcribe_sync, transcribe_audio, get_model_info


class MockSegment:
    def __init__(self, text):
        self.text = text


class MockModel:
    def __init__(self):
        self.model = MagicMock()
        self.model.device = "cpu"

    def transcribe(self, audio_path, language=None, task=None, vad_filter=None, condition_on_previous_text=None):
        segments = [MockSegment("你好世界"), MockSegment("这是测试")]
        info = MagicMock()
        return segments, info


class TestTranscribeSync:
    def test_transcribe_returns_merged_text(self):
        with patch('app.transcribe._load_model', return_value=MockModel()):
            text = _transcribe_sync("fake_path.webm", language="zh")
            assert "你好世界" in text
            assert "这是测试" in text


class TestTranscribeAudio:
    @pytest.mark.asyncio
    async def test_transcribe_audio_bytes(self):
        fake_bytes = b"fake audio content"
        with patch('app.transcribe._load_model', return_value=MockModel()):
            text = await transcribe_audio(fake_bytes, language="zh", suffix=".webm")
            assert "你好世界" in text

    @pytest.mark.asyncio
    async def test_transcribe_audio_auto_language(self):
        fake_bytes = b"fake audio content"
        with patch('app.transcribe._load_model', return_value=MockModel()):
            text = await transcribe_audio(fake_bytes, language=None, suffix=".webm")
            assert "你好世界" in text

    @pytest.mark.asyncio
    async def test_temp_file_cleaned_up(self):
        fake_bytes = b"fake audio content"
        created_files = []
        original_unlink = os.unlink

        def capture_unlink(path):
            created_files.append(path)
            original_unlink(path)

        with patch('app.transcribe._load_model', return_value=MockModel()):
            with patch('os.unlink', side_effect=capture_unlink):
                await transcribe_audio(fake_bytes, language="zh", suffix=".webm")
                assert len(created_files) == 1
                assert not os.path.exists(created_files[0])


class TestGetModelInfo:
    def test_returns_dict_with_expected_keys(self):
        info = get_model_info()
        assert isinstance(info, dict)
        assert "model_size" in info
        assert "loaded" in info
        assert "device" in info

    def test_not_loaded_initially(self):
        with patch('app.transcribe._model', None):
            info = get_model_info()
            assert info["loaded"] is False
            assert info["device"] == "cpu"

    def test_loaded_state(self):
        mock_model = MockModel()
        with patch('app.transcribe._model', mock_model):
            info = get_model_info()
            assert info["loaded"] is True
