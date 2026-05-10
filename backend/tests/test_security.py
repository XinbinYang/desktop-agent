from app.security import redact_sensitive_text, redact_mapping


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
