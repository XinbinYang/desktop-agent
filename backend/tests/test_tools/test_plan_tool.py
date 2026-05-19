import pytest

from app.tools.plan_tool import PlanAskQuestionsTool, PlanWriteDraftTool, PlanUpdateTodosTool


@pytest.fixture
def tool():
    return PlanWriteDraftTool()


@pytest.fixture
def update_tool():
    return PlanUpdateTodosTool()


@pytest.fixture
def ask_tool():
    return PlanAskQuestionsTool()


@pytest.mark.asyncio
async def test_ask_questions_accepts_multiple_blocking_questions(ask_tool):
    result = await ask_tool.execute(questions=[
        {
            "id": "focus",
            "prompt": "Which area should this plan focus on?",
            "options": [
                {"id": "performance", "label": "Performance"},
                {"id": "errors", "label": "Error handling"},
            ],
        },
        {
            "id": "depth",
            "prompt": "How deep should the change go?",
            "options": [
                {"id": "targeted", "label": "Targeted fix"},
                {"id": "hardening", "label": "Test-backed hardening"},
            ],
        },
    ])

    assert not result.error
    assert result.output == "Questions submitted (2). Waiting for user response."
    assert result.metadata["plan_action"] == "questions_submitted"
    assert [q["id"] for q in result.metadata["questions"]] == ["focus", "depth"]


@pytest.mark.asyncio
async def test_empty_args_returns_actionable_error(tool):
    result = await tool.execute()
    assert result.error
    assert "EMPTY arguments" in result.error
    # Must restate the required contract and a usable skeleton.
    assert "'goal'" in result.error
    assert "'todos'" in result.error
    assert "t1" in result.error  # skeleton example present


@pytest.mark.asyncio
async def test_validation_aggregates_all_missing_fields(tool):
    # Only goal provided -> required todos missing.
    result = await tool.execute(goal="Do the thing")
    assert result.error
    assert "'todos'" in result.error
    assert "validation failed" in result.error


@pytest.mark.asyncio
async def test_minimal_call_succeeds_without_markdown_body(tool):
    result = await tool.execute(
        goal="Add TOML support",
        todos=[{"id": "t1", "title": "Add dep + parser branch"}],
    )
    assert not result.error
    payload = result.metadata["plan_action"], result.metadata["payload"]
    assert payload[0] == "draft_submitted"
    # Optional fields coerced to safe defaults so downstream _apply_plan_draft is unaffected.
    p = payload[1]
    assert p["goal"] == "Add TOML support"
    assert p["markdown_body"] == ""
    assert p["assumptions"] == []
    assert p["risks"] == []
    assert p["verification"] == []
    assert p["research_notes"] == ""


@pytest.mark.asyncio
async def test_bad_optional_types_are_coerced_not_rejected(tool):
    result = await tool.execute(
        goal="g",
        steps="not-a-list",
        todos=[{"id": "t1", "title": "t"}],
        assumptions="not-a-list",
        risks=123,
        markdown_body=None,
    )
    assert not result.error
    p = result.metadata["payload"]
    assert p["assumptions"] == []
    assert p["risks"] == []
    assert p["markdown_body"] == ""
    assert p["steps"] == []


@pytest.mark.asyncio
async def test_write_draft_passes_through_context_and_critical_files(tool):
    result = await tool.execute(
        goal="g",
        context="why we do this",
        todos=[{"id": "t1", "title": "t"}],
        critical_files=[
            {"path": "app/x.py", "change": "edit"},
            "app/y.py",
            {"change": "no path - dropped"},
        ],
    )
    assert not result.error
    p = result.metadata["payload"]
    assert p["context"] == "why we do this"
    assert p["critical_files"] == [
        {"path": "app/x.py", "change": "edit"},
        {"path": "app/y.py", "change": ""},
    ]


# ── plan_update_todos ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_todos_empty_args_returns_actionable_error(update_tool):
    result = await update_tool.execute()
    assert result.error
    assert "EMPTY arguments" in result.error
    assert "updates" in result.error


@pytest.mark.asyncio
async def test_update_todos_requires_non_empty_updates(update_tool):
    result = await update_tool.execute(updates=[])
    assert result.error
    assert "non-empty 'updates'" in result.error


@pytest.mark.asyncio
async def test_update_todos_valid_call(update_tool):
    result = await update_tool.execute(updates=[
        {"id": "t1", "status": "completed"},
        {"id": "t2", "status": "in_progress", "note": "starting"},
    ])
    assert not result.error
    assert result.metadata["plan_action"] == "todos_updated"
    assert result.metadata["payload"]["updates"] == [
        {"id": "t1", "status": "completed"},
        {"id": "t2", "status": "in_progress", "note": "starting"},
    ]


@pytest.mark.asyncio
async def test_update_todos_drops_invalid_status_and_missing_id(update_tool):
    result = await update_tool.execute(updates=[
        {"id": "t1", "status": "bogus"},     # invalid status -> dropped
        {"status": "completed"},              # missing id -> dropped
        {"id": "t3", "status": "blocked"},    # valid
    ])
    assert not result.error
    assert result.metadata["payload"]["updates"] == [{"id": "t3", "status": "blocked"}]


@pytest.mark.asyncio
async def test_update_todos_all_invalid_returns_error(update_tool):
    result = await update_tool.execute(updates=[{"id": "t1", "status": "bogus"}])
    assert result.error
    assert "no valid updates" in result.error
