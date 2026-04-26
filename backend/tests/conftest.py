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


@pytest.fixture
def temp_dir(tmp_path):
    """Provide a temporary directory for file tool tests"""
    return tmp_path
