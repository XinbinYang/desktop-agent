"""Tests for slash command system."""
import pytest
from app.commands import (
    CommandInfo,
    BUILTIN_COMMANDS,
    get_commands,
)


class TestCommandInfo:
    def test_command_creation(self):
        cmd = CommandInfo(name="test", description="A test command", args="<arg>", category="test")
        assert cmd.name == "test"
        assert cmd.args == "<arg>"
        assert cmd.category == "test"


class TestBuiltinCommands:
    def test_all_nine_builtins_exist(self):
        assert len(BUILTIN_COMMANDS) == 9

    def test_essential_commands_present(self):
        names = [c.name for c in BUILTIN_COMMANDS]
        assert "help" in names
        assert "clear" in names
        assert "compact" in names
        assert "model" in names
        assert "role" in names
        assert "project" in names
        assert "config" in names
        assert "screenshot" in names
        assert "skills" in names

    def test_no_duplicate_names(self):
        names = [c.name for c in BUILTIN_COMMANDS]
        assert len(names) == len(set(names))

    def test_all_have_descriptions(self):
        for cmd in BUILTIN_COMMANDS:
            assert cmd.description, f"{cmd.name} has no description"

    def test_categories_present(self):
        categories = {c.category for c in BUILTIN_COMMANDS}
        assert "general" in categories
        assert "session" in categories
        assert "tools" in categories
        assert "project" in categories


class TestGetCommands:
    def test_returns_at_least_nine(self):
        cmds = get_commands()
        assert len(cmds) >= 9

    def test_returns_dicts_with_keys(self):
        cmds = get_commands()
        for cmd in cmds:
            assert "name" in cmd
            assert "description" in cmd
            assert "category" in cmd

    def test_help_command_present(self):
        cmds = get_commands()
        names = [c["name"] for c in cmds]
        assert "help" in names

    def test_model_has_args(self):
        cmds = get_commands()
        model = next(c for c in cmds if c["name"] == "model")
        assert model["args"] == "<model_id>"
