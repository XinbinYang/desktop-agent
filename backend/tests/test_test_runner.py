"""Tests for integrated test runner — framework detection and output parsing."""
from pathlib import Path
from app.test_runner import (
    TestResult,
    TestRun,
    detect_framework,
    _parse_pytest_output,
    _parse_jest_output,
    get_last_run,
)


class TestDetectFramework:
    def test_detects_pytest_via_test_files(self, tmp_path):
        (tmp_path / "test_example.py").write_text("def test(): pass")
        fw = detect_framework(str(tmp_path))
        assert fw == "pytest"

    def test_detects_pytest_via_conftest(self, tmp_path):
        (tmp_path / "conftest.py").write_text("import pytest")
        fw = detect_framework(str(tmp_path))
        assert fw == "pytest"

    def test_detects_pytest_via_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]")
        fw = detect_framework(str(tmp_path))
        assert fw == "pytest"

    def test_detects_vitest_via_config(self, tmp_path):
        (tmp_path / "vitest.config.ts").write_text("export default {}")
        fw = detect_framework(str(tmp_path))
        assert fw == "vitest"

    def test_detects_jest_via_config(self, tmp_path):
        (tmp_path / "jest.config.js").write_text("module.exports = {}")
        fw = detect_framework(str(tmp_path))
        assert fw == "jest"

    def test_detects_vitest_via_package_json(self, tmp_path):
        import json
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"test": "vitest run"}})
        )
        fw = detect_framework(str(tmp_path))
        assert fw == "vitest"

    def test_detects_jest_via_package_json(self, tmp_path):
        import json
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"test": "jest --coverage"}})
        )
        fw = detect_framework(str(tmp_path))
        assert fw == "jest"

    def test_empty_project_returns_none(self, tmp_path):
        assert detect_framework(str(tmp_path)) is None


class TestParsePytestOutput:
    def test_passed_and_failed(self):
        output = """
tests/test_auth.py::test_login PASSED [ 50%]
tests/test_auth.py::test_logout FAILED [100%]
"""
        results = _parse_pytest_output(output)
        assert len(results) == 2
        assert results[0].name == "test_login"
        assert results[0].status == "passed"
        assert results[0].file_path == "tests/test_auth.py"
        assert results[1].name == "test_logout"
        assert results[1].status == "failed"

    def test_skipped_and_error(self):
        output = """
tests/test_api.py::TestAPI::test_create SKIPPED [ 33%]
tests/test_api.py::TestAPI::test_delete ERROR [ 66%]
"""
        results = _parse_pytest_output(output)
        assert len(results) == 2
        statuses = {r.name: r.status for r in results}
        assert statuses.get("TestAPI::test_create") == "skipped"
        assert statuses.get("TestAPI::test_delete") == "error"

    def test_xfail_and_xpass(self):
        output = """
tests/test_edge.py::test_flaky XFAIL [ 50%]
tests/test_edge.py::test_unexpected XPASS [100%]
"""
        results = _parse_pytest_output(output)
        assert len(results) == 2
        assert results[0].status == "skipped"  # XFAIL -> skipped
        assert results[1].status == "passed"   # XPASS -> passed

    def test_empty_output(self):
        assert _parse_pytest_output("") == []

    def test_class_based_test(self):
        output = "tests/test_models.py::TestUser::test_create PASSED [100%]"
        results = _parse_pytest_output(output)
        assert len(results) == 1
        assert results[0].name == "TestUser::test_create"


class TestParseJestOutput:
    def test_passed_test(self):
        output = " ✓ login renders correctly (45 ms)"
        results = _parse_jest_output(output)
        assert len(results) == 1
        assert results[0].status == "passed"
        assert results[0].duration_ms == 45

    def test_failed_test(self):
        output = " ✗ login fails with error (12 ms)"
        results = _parse_jest_output(output)
        assert len(results) == 1
        assert results[0].status == "failed"

    def test_skipped_test(self):
        output = " ○ login skipped for now (0 ms)"
        results = _parse_jest_output(output)
        assert len(results) == 1
        assert results[0].status == "skipped"


class TestTestRun:
    def test_dataclass_defaults(self):
        run = TestRun(run_id="test1")
        assert run.total == 0
        assert run.passed == 0
        assert run.results == []

    def test_get_last_run_initial(self):
        # Initially None (no test runs yet in this process)
        last = get_last_run()
        # May be None from previous tests, just verify it's callable
        assert last is None or isinstance(last, TestRun)
