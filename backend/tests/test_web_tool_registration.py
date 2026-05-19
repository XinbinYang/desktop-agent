def test_web_tools_available_to_all_static_tools():
    from app.tools import get_tool, list_tool_names

    names = set(list_tool_names())
    assert "web_search" in names
    assert "web_fetch" in names
    assert get_tool("web_search").name == "web_search"
    assert get_tool("web_fetch").name == "web_fetch"


def test_web_tools_available_to_coding_agent_schema():
    from app.tools import build_tools_description, get_tool_schemas

    names = {s["function"]["name"] for s in get_tool_schemas(agent_type="coding")}
    assert "web_search" in names
    assert "web_fetch" in names

    desc = build_tools_description(agent_type="coding")
    assert "web_search" in desc
    assert "web_fetch" in desc


def test_web_tools_are_plan_readonly_tools():
    from app.agent import READONLY_PLAN_TOOLS

    assert "web_search" in READONLY_PLAN_TOOLS
    assert "web_fetch" in READONLY_PLAN_TOOLS


def test_worker_profiles_include_web_tools():
    from app.worker import WORKER_PROFILES

    for profile in ("code", "general", "architect", "explorer", "reviewer", "code-expert"):
        tools = set(WORKER_PROFILES[profile].tools)
        assert "web_search" in tools
        assert "web_fetch" in tools
