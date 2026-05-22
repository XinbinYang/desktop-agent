"""Shared fixtures for collaboration module tests."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

# Ensure backend is on path
BACKEND_ROOT = Path(__file__).parent.parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DESKTOP_AGENT_USER_DATA_DIR",
    str(Path(tempfile.gettempdir()) / "desktop-agent-pytest-collab"),
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> Any:
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def sample_task_packet_data() -> Dict[str, Any]:
    return _load_fixture("sample_packets.json")["basic"]


@pytest.fixture
def sample_events() -> List[Dict[str, Any]]:
    return _load_fixture("sample_events.json")["execute_with_tools"]


@pytest.fixture
def empty_events() -> List[Dict[str, Any]]:
    return []


@pytest.fixture
def pass_events() -> List[Dict[str, Any]]:
    """Events representing a successful execution with ACCEPTANCE: PASS."""
    return _load_fixture("sample_events.json")["pass_run"]


@pytest.fixture
def fail_events() -> List[Dict[str, Any]]:
    """Events representing a failed execution with ACCEPTANCE: FAIL."""
    return _load_fixture("sample_events.json")["fail_run"]
