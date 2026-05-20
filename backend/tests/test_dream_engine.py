import pytest

from app.agents.dream import DreamEngine
from app.agents.manager import AgentManager


@pytest.mark.asyncio
async def test_dream_run_handles_empty_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
    memory_dir = AgentManager._memory_dir()
    memory_dir.mkdir(parents=True)

    result = await DreamEngine.run()

    assert result["light_sleep"]["candidates_found"] == 0
    assert result["deep_sleep"]["passed"] == 0
    assert result["rem"] == {"patterns": [], "suggestions": []}
