from app.windows_asyncio import _is_retryable_accept_error


def test_winerror_64_accept_error_is_retryable():
    exc = OSError(22, "The specified network name is no longer available")
    exc.winerror = 64

    assert _is_retryable_accept_error(exc) is True


def test_non_windows_accept_error_is_not_retryable():
    exc = OSError(22, "Invalid argument")
    exc.winerror = 123

    assert _is_retryable_accept_error(exc) is False
