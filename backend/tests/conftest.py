import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure backend is on path
BACKEND_ROOT = Path(__file__).parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport


@pytest.fixture(scope="session")
def client():
    """Synchronous FastAPI TestClient"""
    from app.main import app
    return TestClient(app)


@pytest.fixture
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
        yield mock


@pytest.fixture(autouse=True)
def reset_config_cache():
    """Reset config cache before each test"""
    from app import config
    config._config = None
    yield
    config._config = None


@pytest.fixture(autouse=True)
def clean_sessions(monkeypatch):
    """Lightweight: clear in-memory sessions without importing litellm cascade."""
    # Delay import to avoid triggering app.models -> litellm at fixture evaluation
    from app.agent import _sessions
    _sessions.clear()
    yield
    _sessions.clear()


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

    ProjectManager._current_project = None
    CredentialManager._credentials_cache = None

    yield

    ProjectManager._current_project = None
    CredentialManager._credentials_cache = None


@pytest.fixture
def temp_dir():
    """Provide a temporary directory inside the project root for file tool tests"""
    test_dir = BACKEND_ROOT / "tests" / "tmp"
    test_dir.mkdir(parents=True, exist_ok=True)
    import tempfile
    with tempfile.TemporaryDirectory(dir=str(test_dir)) as d:
        yield Path(d)
