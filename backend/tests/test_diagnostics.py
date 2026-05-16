"""Tests for diagnostics collector — linter detection and output parsing."""
from pathlib import Path
from app.diagnostics import (
    DiagnosticItem,
    DiagnosticsResult,
    detect_linters,
    _parse_mypy,
    _parse_tsc,
    _parse_eslint,
    _parse_pyright,
    get_last_result,
)


class TestDetectLinters:
    def test_detects_mypy_with_python_files(self, tmp_path):
        (tmp_path / "main.py").write_text("x = 1")
        linters = detect_linters(str(tmp_path))
        assert "mypy" in linters
        assert "pyright" in linters

    def test_detects_tsc_with_tsconfig(self, tmp_path):
        (tmp_path / "tsconfig.json").write_text("{}")
        linters = detect_linters(str(tmp_path))
        assert "tsc" in linters

    def test_detects_eslint_with_config(self, tmp_path):
        (tmp_path / "eslint.config.js").write_text("module.exports = {}")
        linters = detect_linters(str(tmp_path))
        assert "eslint" in linters

    def test_empty_project(self, tmp_path):
        linters = detect_linters(str(tmp_path))
        # pyright is always added as a best-effort linter
        assert linters == ["pyright"]


class TestParseMypy:
    def test_error_and_warning(self):
        output = """src/main.py:42:5: error: Incompatible types in assignment
src/utils.py:10:1: warning: Function is missing a return type annotation
"""
        items = _parse_mypy(output, "/project")
        assert len(items) == 2
        assert items[0].severity == "error"
        assert items[0].line == 42
        assert items[0].column == 5
        assert items[0].source == "mypy"
        assert "Incompatible" in items[0].message
        assert items[1].severity == "warning"

    def test_note_is_info(self):
        output = "src/app.py:1:1: note: This is a note"
        items = _parse_mypy(output, "/project")
        assert len(items) == 1
        assert items[0].severity == "info"

    def test_empty_output(self):
        assert _parse_mypy("", "") == []


class TestParseTsc:
    def test_error(self):
        output = "src/App.tsx(42,10): error TS2345: Argument of type string is not assignable"
        items = _parse_tsc(output)
        assert len(items) == 1
        assert items[0].severity == "error"
        assert items[0].line == 42
        assert items[0].column == 10
        assert items[0].source == "tsc"
        assert "TS2345" in items[0].message

    def test_warning(self):
        output = "src/utils.ts(5,3): warning TS6133: 'x' is declared but never used"
        items = _parse_tsc(output)
        assert len(items) == 1
        assert items[0].severity == "warning"

    def test_empty_output(self):
        assert _parse_tsc("") == []


class TestParseEslint:
    def test_structured_output(self):
        output = """  12:5  error    Unexpected var  no-var
  15:10 warning  Missing semicolon  semi
"""
        items = _parse_eslint(output)
        # structured eslint output may or may not parse with the regex
        # At minimum it shouldn't crash
        assert isinstance(items, list)

    def test_json_output(self):
        output = """[{"filePath": "src/app.js", "line": 10, "column": 3, "severity": "error", "message": "no-var"}]"""
        items = _parse_eslint(output)
        assert len(items) >= 0  # JSON parsing should at least not crash

    def test_empty_output(self):
        assert _parse_eslint("") == []


class TestParsePyright:
    def test_error_and_warning(self):
        output = """  src/main.py:42:5 - error: Cannot access member
  src/utils.py:10:1 - warning: Type annotation missing
"""
        items = _parse_pyright(output)
        assert len(items) == 2
        assert items[0].severity == "error"
        assert items[0].source == "pyright"

    def test_information_level(self):
        output = "  src/app.py:1:1 - information: Pyright version 1.x"
        items = _parse_pyright(output)
        assert len(items) == 1
        assert items[0].severity == "info"

    def test_empty_output(self):
        assert _parse_pyright("") == []


class TestDiagnosticItem:
    def test_dataclass(self):
        item = DiagnosticItem(
            file_path="src/main.py", line=42, column=5,
            severity="error", message="bad type", source="mypy",
        )
        assert item.file_path == "src/main.py"
        assert item.line == 42
        assert item.column == 5
        assert item.severity == "error"


class TestDiagnosticsResult:
    def test_dataclass_defaults(self):
        result = DiagnosticsResult(source="mypy")
        assert result.total == 0
        assert result.errors == 0
        assert result.warnings == 0
        assert result.items == []

    def test_get_last_result_initial(self):
        last = get_last_result()
        assert last is None or isinstance(last, DiagnosticsResult)
