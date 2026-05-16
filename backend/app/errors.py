"""Structured error types for consistent error handling across the agent stack."""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional


class ErrorCategory(str, Enum):
    """Machine-readable error categories for frontend differentiation."""
    AUTH = "auth"
    NETWORK = "network"
    RATE_LIMIT = "rate_limit"
    PROVIDER = "provider"           # Model provider error (5xx, bad gateway, etc.)
    TIMEOUT = "timeout"
    CONTEXT_LENGTH = "context_length"
    SANDBOX = "sandbox"             # Guardrail / worktree / permissions
    TOOL_FAILURE = "tool_failure"   # Tool execution failed
    TOOL_NOT_FOUND = "tool_not_found"
    VALIDATION = "validation"       # Bad input / invalid arguments
    NOT_FOUND = "not_found"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


# ── structured error payload builders ───────────────────────────────────────

def _error_dict(
    category: ErrorCategory,
    message: str,
    *,
    retryable: bool = False,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "category": category.value,
        "message": message,
        "retryable": retryable,
    }
    if details:
        d["details"] = details
    return d


def auth_error(message: str = "Unauthorized") -> Dict[str, Any]:
    return _error_dict(ErrorCategory.AUTH, message, retryable=False)


def network_error(message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _error_dict(ErrorCategory.NETWORK, message, retryable=True, details=details)


def rate_limit_error(message: str, retry_after: Optional[int] = None) -> Dict[str, Any]:
    details = {"retry_after": retry_after} if retry_after is not None else None
    return _error_dict(ErrorCategory.RATE_LIMIT, message, retryable=True, details=details)


def provider_error(message: str, status_code: Optional[int] = None) -> Dict[str, Any]:
    details = {"status_code": status_code} if status_code is not None else None
    return _error_dict(ErrorCategory.PROVIDER, message, retryable=True, details=details)


def timeout_error(message: str = "Request timed out") -> Dict[str, Any]:
    return _error_dict(ErrorCategory.TIMEOUT, message, retryable=True)


def context_length_error(message: str = "Context length exceeded") -> Dict[str, Any]:
    return _error_dict(ErrorCategory.CONTEXT_LENGTH, message, retryable=False)


def sandbox_error(message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _error_dict(ErrorCategory.SANDBOX, message, retryable=False, details=details)


def tool_failure_error(message: str, tool_name: Optional[str] = None) -> Dict[str, Any]:
    details = {"tool_name": tool_name} if tool_name else None
    return _error_dict(ErrorCategory.TOOL_FAILURE, message, retryable=False, details=details)


def tool_not_found_error(tool_name: str) -> Dict[str, Any]:
    return _error_dict(
        ErrorCategory.TOOL_NOT_FOUND,
        f"Unknown tool: {tool_name}",
        retryable=False,
        details={"tool_name": tool_name},
    )


def validation_error(message: str) -> Dict[str, Any]:
    return _error_dict(ErrorCategory.VALIDATION, message, retryable=False)


def not_found_error(message: str) -> Dict[str, Any]:
    return _error_dict(ErrorCategory.NOT_FOUND, message, retryable=False)


def internal_error(message: str = "Internal server error") -> Dict[str, Any]:
    return _error_dict(ErrorCategory.INTERNAL, message, retryable=False)


def unknown_error(message: str = "An unknown error occurred") -> Dict[str, Any]:
    return _error_dict(ErrorCategory.UNKNOWN, message, retryable=False)


# ── legacy-compatible error response for REST endpoints ─────────────────────

def error_response(
    category: ErrorCategory,
    message: str,
    *,
    retryable: bool = False,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a JSON-serializable error dict for REST endpoint responses."""
    return {"error": _error_dict(category, message, retryable=retryable, details=details)}


# ── error categorizer for exception translation ─────────────────────────────

def categorize_exception(exc: Exception) -> Dict[str, Any]:
    """Translate a caught exception into a structured error dict.

    Handles common API / tool / guardrail exception types. Falls back to
    :func:`unknown_error` for unrecognised exceptions.
    """
    import asyncio

    exc_str = str(exc)

    # Timeout
    if isinstance(exc, asyncio.TimeoutError) or "timeout" in exc_str.lower():
        return timeout_error(exc_str or "Request timed out")

    # Rate limit
    if "rate_limit" in exc_str.lower() or "429" in exc_str:
        return rate_limit_error(exc_str)

    # Auth
    if any(kw in exc_str.lower() for kw in ("unauthorized", "auth", "401", "403")):
        return auth_error(exc_str)

    # Context length
    if any(kw in exc_str.lower() for kw in ("context_length", "token", "max_tokens")):
        return context_length_error(exc_str)

    # Provider / upstream
    if any(kw in exc_str.lower() for kw in ("502", "503", "504", "bad gateway", "service unavailable")):
        return provider_error(exc_str)

    return unknown_error(exc_str or "An unknown error occurred")
