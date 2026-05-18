from pathlib import Path

import pytest
from app.security import redact_sensitive_text, redact_mapping, resolve_under_base


class TestRedactSensitiveText:
    def test_authorization_basic_header(self):
        out = redact_sensitive_text("Authorization: Basic dXNlcjpwYXNz=")
        assert "dXNlcjpwYXNz" not in out
        assert "[REDACTED]" in out

    def test_authorization_bearer_header(self):
        out = redact_sensitive_text("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig")
        assert "eyJhbGciOiJIUzI1NiJ9" not in out
        assert "[REDACTED]" in out

    def test_x_api_key_header(self):
        out = redact_sensitive_text("x-api-key: sk-ant-abcdef1234567890")
        assert "abcdef1234567890" not in out
        assert "[REDACTED]" in out

    def test_github_pat(self):
        out = redact_sensitive_text("token=ghp_1234567890abcdefghij here")
        assert "ghp_1234567890abcdefghij" not in out
        assert "[REDACTED]" in out

    def test_github_app_token(self):
        for prefix in ("ghp_", "ghs_", "gho_", "ghu_", "ghr_"):
            secret = f"{prefix}abcdefghijklmnop"
            out = redact_sensitive_text(secret)
            assert secret not in out

    def test_gitlab_pat(self):
        out = redact_sensitive_text("clone https://oauth2:glpat-AbCdEfGhIjKlMnOp@gitlab.com/x.git")
        assert "glpat-AbCdEfGhIjKlMnOp" not in out
        assert "[REDACTED]" in out

    def test_openai_sk_key(self):
        out = redact_sensitive_text("OPENAI_API_KEY=sk-abc123def456ghi789jkl")
        assert "sk-abc123def456ghi789jkl" not in out

    def test_slack_token(self):
        out = redact_sensitive_text("xoxp-1234567890-abcdef-ghijkl")
        assert "xoxp-1234567890-abcdef-ghijkl" not in out

    def test_aws_access_key(self):
        out = redact_sensitive_text("AKIAIOSFODNN7EXAMPLE\nasia: ASIAIOSFODNN7EXAMPLE")
        assert "AKIAIOSFODNN7EXAMPLE" not in out
        assert "ASIAIOSFODNN7EXAMPLE" not in out

    def test_non_secret_text_unchanged(self):
        out = redact_sensitive_text("hello world\nbranch main\nfile.py:42")
        assert out == "hello world\nbranch main\nfile.py:42"


class TestRedactMapping:
    def test_redacts_token_field(self):
        out = redact_mapping({"username": "u", "token": "ghp_secret123456789012", "host": "github.com"})
        assert out["username"] == "u"
        assert out["host"] == "github.com"
        assert out["token"] == "[REDACTED]"

    def test_redacts_password_field(self):
        out = redact_mapping({"password": "hunter2"})
        assert out["password"] == "[REDACTED]"

    def test_keeps_empty_values_visible(self):
        """An empty token isn't a secret; passing through avoids ambiguity in logs."""
        out = redact_mapping({"token": ""})
        assert out["token"] == ""


class TestResolveUnderBase:
    """Path anchoring tests for resolve_under_base.

    The backend process runs with cwd=backend/, so any cwd-relative resolution
    would silently map AGENTS/personal/USER.md -> backend/AGENTS/personal/USER.md.
    These tests verify relative paths are always anchored to *base*, not cwd.
    """

    @pytest.fixture
    def repo_root(self) -> Path:
        """Repository root = backend/app security.py is at backend/app/security.py
        so parents[2] from that file = repo root."""
        from app.runtime_paths import repo_root as rr
        return rr()

    def test_relative_path_anchored_to_base_not_cwd(self, repo_root):
        """Relative path 'AGENTS/personal/USER.md' must resolve under repo_root
        even when cwd is backend/."""
        result, err = resolve_under_base(
            "AGENTS/personal/USER.md",
            repo_root,
            allow_relative=False,
        )
        assert err is None, f"unexpected error: {err}"
        assert result == (repo_root / "AGENTS/personal/USER.md").resolve(), (
            f"Expected {repo_root / 'AGENTS/personal/USER.md'}, got {result}"
        )

    def test_absolute_path_still_works(self, repo_root):
        """Absolute paths should still resolve normally."""
        target = repo_root / "AGENTS" / "personal" / "USER.md"
        result, err = resolve_under_base(str(target), repo_root, allow_relative=False)
        assert err is None
        assert result == target.resolve()

    def test_out_of_bounds_still_blocked(self, repo_root):
        """Path traversal escaping base must still be blocked."""
        result, err = resolve_under_base(
            "../../../outside.txt", repo_root, allow_relative=False
        )
        assert err is not None
        assert "escapes" in err

    def test_relative_with_allow_relative_true_also_anchored(self, repo_root):
        """Even with allow_relative=True, path resolves under base, not cwd."""
        result, err = resolve_under_base(
            "AGENTS/personal/USER.md",
            repo_root,
            allow_relative=True,
        )
        assert err is None
        assert result == (repo_root / "AGENTS/personal/USER.md").resolve(), (
            f"Expected {repo_root / 'AGENTS/personal/USER.md'}, got {result}"
        )
