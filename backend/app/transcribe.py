import os
import tempfile
import asyncio
from typing import Optional
import aiofiles

from app.runtime_paths import runtime_dir

# 全局单例模型缓存
_model = None
_model_size = os.environ.get("WHISPER_MODEL", "tiny")  # tiny/base/small/medium/large

def _load_model():
    """延迟加载 Whisper 模型（线程安全由单例保证）。"""
    global _model
    if _model is not None:
        return _model

    from faster_whisper import WhisperModel

    # 根据硬件自动选择参数（不强制依赖 torch）
    device = "cpu"
    compute_type = "int8"
    try:
        import torch
        if torch.cuda.is_available():
            device = "cuda"
            compute_type = "float16"
    except Exception:
        pass

    _model = WhisperModel(
        _model_size,
        device=device,
        compute_type=compute_type,
        download_root=str(runtime_dir("models") / "whisper"),
    )
    return _model


def _transcribe_sync(audio_path: str, language: Optional[str] = "zh") -> str:
    """同步转录（在线程池中运行，避免阻塞事件循环）。"""
    model = _load_model()
    segments, info = model.transcribe(
        audio_path,
        language=language,
        task="transcribe",
        vad_filter=True,
        condition_on_previous_text=True,
    )
    # 合并所有片段
    texts = [segment.text.strip() for segment in segments]
    return " ".join(texts).strip()


async def transcribe_audio(
    audio_bytes: bytes,
    language: Optional[str] = "zh",
    suffix: str = ".webm"
) -> str:
    """转录音频字节流，返回识别文本。

    Args:
        audio_bytes: 音频文件二进制内容
        language: 语言代码，默认中文。设为 None 则自动检测。
        suffix: 临时文件后缀，应与原始格式匹配（.webm / .wav / .mp3）
    """
    # 写入临时文件（faster-whisper 需要文件路径）
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(
            None, _transcribe_sync, tmp_path, language
        )
        return text
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def get_model_info() -> dict:
    """获取当前加载的模型信息。"""
    return {
        "model_size": _model_size,
        "loaded": _model is not None,
        "device": "cuda" if _model and hasattr(_model, 'model') and 'cuda' in str(getattr(_model.model, 'device', '')) else "cpu",
    }
