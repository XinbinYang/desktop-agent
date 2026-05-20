from __future__ import annotations

import os
from typing import Any


_PATCHED = False
_RETRYABLE_ACCEPT_WINERRORS = {64, 995, 10053, 10054}


def _is_retryable_accept_error(exc: BaseException) -> bool:
    return getattr(exc, "winerror", None) in _RETRYABLE_ACCEPT_WINERRORS


def patch_windows_proactor_accept() -> None:
    """Keep Windows Proactor servers listening after transient AcceptEx errors.

    On Windows, a client-side abort during AcceptEx can surface as WinError 64.
    CPython's Proactor loop closes the listening socket for any accept OSError,
    which leaves uvicorn alive but no longer listening on 127.0.0.1:8765.
    Retrying these known transient errors preserves Proactor subprocess support.
    """
    global _PATCHED
    if _PATCHED or os.name != "nt":
        return

    try:
        from asyncio import exceptions, proactor_events, trsock
    except ImportError:
        return

    original = proactor_events.BaseProactorEventLoop._start_serving
    if getattr(original, "_desktop_agent_retry_accept", False):
        _PATCHED = True
        return

    def _start_serving(
        self: Any,
        protocol_factory: Any,
        sock: Any,
        sslcontext: Any = None,
        server: Any = None,
        backlog: int = 100,
        ssl_handshake_timeout: Any = None,
        ssl_shutdown_timeout: Any = None,
    ) -> None:
        def loop(f: Any = None) -> None:
            try:
                if f is not None:
                    conn, addr = f.result()
                    if self._debug:
                        proactor_events.logger.debug(
                            "%r got a new connection from %r: %r",
                            server,
                            addr,
                            conn,
                        )
                    protocol = protocol_factory()
                    if sslcontext is not None:
                        self._make_ssl_transport(
                            conn,
                            protocol,
                            sslcontext,
                            server_side=True,
                            extra={"peername": addr},
                            server=server,
                            ssl_handshake_timeout=ssl_handshake_timeout,
                            ssl_shutdown_timeout=ssl_shutdown_timeout,
                        )
                    else:
                        self._make_socket_transport(
                            conn,
                            protocol,
                            extra={"peername": addr},
                            server=server,
                        )
                if self.is_closed():
                    return
                f = self._proactor.accept(sock)
            except OSError as exc:
                fileno = sock.fileno()
                if fileno != -1 and _is_retryable_accept_error(exc):
                    self._accept_futures.pop(fileno, None)
                    self.call_exception_handler({
                        "message": "Transient accept failed on a socket; retrying",
                        "exception": exc,
                        "socket": trsock.TransportSocket(sock),
                    })
                    self.call_later(0.05, loop)
                    return
                if fileno != -1:
                    self.call_exception_handler({
                        "message": "Accept failed on a socket",
                        "exception": exc,
                        "socket": trsock.TransportSocket(sock),
                    })
                    sock.close()
                elif self._debug:
                    proactor_events.logger.debug(
                        "Accept failed on socket %r",
                        sock,
                        exc_info=True,
                    )
            except exceptions.CancelledError:
                sock.close()
            else:
                self._accept_futures[sock.fileno()] = f
                f.add_done_callback(loop)

        self.call_soon(loop)

    _start_serving._desktop_agent_retry_accept = True  # type: ignore[attr-defined]
    proactor_events.BaseProactorEventLoop._start_serving = _start_serving
    _PATCHED = True
