"""Tests for structured error system."""
import asyncio
from app.errors import (
    ErrorCategory,
    auth_error,
    network_error,
    rate_limit_error,
    provider_error,
    timeout_error,
    context_length_error,
    sandbox_error,
    tool_failure_error,
    tool_not_found_error,
    validation_error,
    not_found_error,
    internal_error,
    unknown_error,
    error_response,
    categorize_exception,
)


class TestErrorCategories:
    def test_all_categories_exist(self):
        assert len(ErrorCategory) == 13

    def test_category_values(self):
        assert ErrorCategory.AUTH == "auth"
        assert ErrorCategory.NETWORK == "network"
        assert ErrorCategory.RATE_LIMIT == "rate_limit"
        assert ErrorCategory.SANDBOX == "sandbox"


class TestErrorBuilders:
    def test_auth_error(self):
        e = auth_error("bad token")
        assert e["category"] == "auth"
        assert e["retryable"] == False
        assert "bad token" in e["message"]

    def test_network_error_retryable(self):
        e = network_error("timeout")
        assert e["category"] == "network"
        assert e["retryable"] == True

    def test_rate_limit_with_retry_after(self):
        e = rate_limit_error("slow down", retry_after=30)
        assert e["category"] == "rate_limit"
        assert e["details"]["retry_after"] == 30

    def test_provider_error_with_status(self):
        e = provider_error("bad gateway", status_code=502)
        assert e["category"] == "provider"
        assert e["details"]["status_code"] == 502

    def test_timeout_error(self):
        e = timeout_error()
        assert e["category"] == "timeout"
        assert e["retryable"] == True

    def test_context_length_error_not_retryable(self):
        e = context_length_error()
        assert e["category"] == "context_length"
        assert e["retryable"] == False

    def test_sandbox_error(self):
        e = sandbox_error("blocked by guardrail")
        assert e["category"] == "sandbox"

    def test_tool_failure_error(self):
        e = tool_failure_error("command failed", tool_name="shell_execute")
        assert e["category"] == "tool_failure"
        assert e["details"]["tool_name"] == "shell_execute"

    def test_tool_not_found_error(self):
        e = tool_not_found_error("unknown_tool")
        assert e["category"] == "tool_not_found"

    def test_validation_error(self):
        e = validation_error("invalid input")
        assert e["category"] == "validation"
        assert e["retryable"] == False

    def test_not_found_error(self):
        e = not_found_error("session missing")
        assert e["category"] == "not_found"

    def test_internal_error(self):
        e = internal_error()
        assert e["category"] == "internal"

    def test_unknown_error(self):
        e = unknown_error("something happened")
        assert e["category"] == "unknown"


class TestErrorResponse:
    def test_error_response_wraps_in_dict(self):
        resp = error_response(ErrorCategory.AUTH, "Unauthorized")
        assert "error" in resp
        assert resp["error"]["category"] == "auth"
        assert resp["error"]["retryable"] == False

    def test_error_response_with_details(self):
        resp = error_response(ErrorCategory.NETWORK, "timeout", retryable=True, details={"host": "api"})
        assert resp["error"]["retryable"] == True
        assert resp["error"]["details"]["host"] == "api"


class TestCategorizeException:
    def test_asyncio_timeout(self):
        exc = asyncio.TimeoutError("timed out")
        e = categorize_exception(exc)
        assert e["category"] == "timeout"

    def test_string_timeout(self):
        e = categorize_exception(Exception("connection timeout after 30s"))
        assert e["category"] == "timeout"

    def test_rate_limit_429(self):
        e = categorize_exception(Exception("429 Too Many Requests"))
        assert e["category"] == "rate_limit"

    def test_unauthorized(self):
        e = categorize_exception(Exception("401 Unauthorized"))
        assert e["category"] == "auth"

    def test_context_length(self):
        e = categorize_exception(Exception("context_length_exceeded: max_tokens"))
        assert e["category"] == "context_length"

    def test_bad_gateway(self):
        e = categorize_exception(Exception("502 Bad Gateway from provider"))
        assert e["category"] == "provider"

    def test_unknown_fallback(self):
        e = categorize_exception(Exception("some random error"))
        assert e["category"] == "unknown"

    def test_rate_limit_keyword(self):
        e = categorize_exception(Exception("rate_limit exceeded"))
        assert e["category"] == "rate_limit"
