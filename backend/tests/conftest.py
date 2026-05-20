import pytest
import pytest_asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure backend is on path
BACKEND_ROOT = Path(__file__).parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

TEST_USER_DATA_DIR = Path(tempfile.gettempdir()) / "desktop-agent-pytest-user-data"
os.environ.setdefault("DESKTOP_AGENT_USER_DATA_DIR", str(TEST_USER_DATA_DIR))

from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport


@pytest.fixture(scope="session")
def client():
    """Synchronous FastAPI TestClient"""
    from app.main import app
    return TestClient(app)


@pytest_asyncio.fixture
async def async_client():
    """Async HTTP client for ASGI app"""
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_litellm():
    """Mock LiteLLM acompletion to avoid real API calls"""
    with patch("app.models.acompletion") as mock:
        mock.return_value = MagicMock()
        mock.return_value.model_dump.return_value = {
            "choices": [{
                "message": {
                    "content": "Mock response",
                    "role": "assistant"
                }
            }]
        }
        # Prevent MagicMock auto-creation of reasoning_content via getattr
        mock.return_value.choices[0].message.reasoning_content = None
        yield mock


@pytest.fixture
def mock_litellm_with_tool_call():
    """Mock LiteLLM returning a tool call"""
    with patch("app.models.acompletion") as mock:
        mock.return_value = MagicMock()
        mock.return_value.model_dump.return_value = {
            "choices": [{
                "message": {
                    "content": "",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_screen_size",
                            "arguments": "{}"
                        }
                    }]
                }
            }]
        }
        mock.return_value.choices[0].message.reasoning_content = None
        yield mock


@pytest.fixture(autouse=True)
def reset_config_cache(monkeypatch, tmp_path):
    """Reset config cache and isolate writes to a temp file."""
    from app import config

    config._config = None
    # Use a subdirectory so the temp models.yaml doesn't pollute tmp_path
    # for other tests (e.g. RAGEngine tests that index files from tmp_path).
    config_dir = tmp_path / ".config-isolation"
    config_dir.mkdir()
    temp_config = config_dir / "models.yaml"
    if config.CONFIG_PATH.exists():
        import shutil
        shutil.copy2(config.CONFIG_PATH, temp_config)
    else:
        from app.runtime_paths import bundled_config_path
        import shutil
        bundled_config = bundled_config_path()
        if bundled_config.exists():
            shutil.copy2(bundled_config, temp_config)
        else:
            temp_config.write_text(
                "providers: {}\nsettings: {default_model: '', default_provider: '', max_iterations: 50}\n",
                encoding="utf-8",
            )
    monkeypatch.setattr(config, "CONFIG_PATH", temp_config)
    config._config = None

    yield

    config._config = None


@pytest.fixture(autouse=True)
def reset_local_auth(monkeypatch):
    """Local API auth is opt-in per test."""
    monkeypatch.delenv("DESKTOP_AGENT_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("DESKTOP_AGENT_USER_DATA_DIR", str(TEST_USER_DATA_DIR))


@pytest.fixture(autouse=True)
def clean_sessions(monkeypatch):
    """Isolate runtime transcript/memory state and clear in-memory sessions."""
    # Delay import to avoid triggering app.models -> litellm at fixture evaluation
    from app.agent import _sessions
    from app.session_runtime import _session_runtimes

    shutil.rmtree(TEST_USER_DATA_DIR, ignore_errors=True)
    _sessions.clear()
    _session_runtimes.clear()
    yield
    _sessions.clear()
    _session_runtimes.clear()
    shutil.rmtree(TEST_USER_DATA_DIR, ignore_errors=True)


@pytest.fixture
def isolate_projects(tmp_path, monkeypatch):
    """Isolate project/credential directories for tests that need them."""
    from app.credential_manager import CredentialManager
    from app.project_manager import ProjectManager
    import app.credential_manager as credential_manager
    import app.project_manager as project_manager

    runtime_dir = tmp_path / "runtime"
    projects_dir = runtime_dir / "projects"
    projects_dir.mkdir(parents=True)

    monkeypatch.setattr(project_manager, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(project_manager, "RECENT_FILE", projects_dir / "recent.json")
    monkeypatch.setattr(credential_manager, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(credential_manager, "CREDENTIALS_FILE", projects_dir / "credentials.json")
    monkeypatch.setattr(credential_manager, "CREDENTIALS_FILE_V2", projects_dir / "credentials.dpapi")
    monkeypatch.setattr(credential_manager, "CREDENTIALS_BACKUP_FILE", projects_dir / "credentials.json.bak")

    ProjectManager._current_project = None
    CredentialManager._credentials_cache = None

    yield

    ProjectManager._current_project = None
    CredentialManager._credentials_cache = None


def _make_stream_mock(mock_response: dict):
    """Create an async generator callable to replace chat_completion_stream in tests.

    Converts legacy non-streaming mock_response dicts into a streaming-compatible
    replacement. Yields text_delta events for content (split into a few chunks),
    then a 'done' event wrapping the full response.
    """
    async def _stream(*args, **kwargs):
        msg = mock_response.get("choices", [{}])[0].get("message", {})
        content = msg.get("content", "")
        if content:
            chunk_size = max(1, len(content) // 4)
            for i in range(0, len(content), chunk_size):
                yield {"type": "text_delta", "text": content[i:i + chunk_size]}
        yield {"type": "done", "response": mock_response}
    return _stream

@pytest.fixture
def temp_dir():
    """Provide a temporary directory outside the repo working tree."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)
