from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, AsyncIterator, Callable, Dict, Optional, Set

from app.agent import AgentSession
from app.errors import categorize_exception
from app.tools.worker_tool import reset_worker_event_callback, set_worker_event_callback


RunFactory = Callable[[], AsyncIterator[Dict[str, Any]]]


class SessionRuntime:
    """Owns the live background run for one chat session.

    WebSocket connections are transient UI transports. The agent run belongs
    to the session itself so a renderer reload, HMR reconnect, pane remount, or
    short network break cannot cancel the underlying task.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._subscribers: Set[asyncio.Queue[Dict[str, Any]]] = set()
        self._lock = asyncio.Lock()
        self._deleted = False

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def is_deleted(self) -> bool:
        return self._deleted

    def subscribe(self) -> asyncio.Queue[Dict[str, Any]]:
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: Dict[str, Any]) -> None:
        if self._deleted:
            return
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                with suppress(asyncio.QueueFull):
                    queue.put_nowait(event)

    async def start(self, session: AgentSession, run_factory: RunFactory) -> None:
        async with self._lock:
            if self._deleted:
                raise RuntimeError(f"Session {self.session_id} has been deleted")
            await self._cancel_locked(session, broadcast=False)
            self._loop = asyncio.get_running_loop()
            self._task = asyncio.create_task(self._run(run_factory))

    async def cancel(self, session: Optional[AgentSession] = None, *, broadcast: bool = True) -> None:
        async with self._lock:
            await self._cancel_locked(session, broadcast=broadcast)

    async def terminate(self, session: Optional[AgentSession] = None) -> None:
        async with self._lock:
            self._deleted = True
            await self._cancel_locked(session, broadcast=False)
            self._subscribers.clear()

    async def _cancel_locked(self, session: Optional[AgentSession], *, broadcast: bool) -> None:
        if session is not None:
            session.cancel()
        task = self._task
        if task is None or task.done():
            self._task = None
            self._loop = None
            return
        owner_loop = self._loop
        current_loop = asyncio.get_running_loop()
        if owner_loop is not None and owner_loop is not current_loop and owner_loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._cancel_task_on_owner_loop(task), owner_loop)
            await asyncio.wrap_future(future)
        else:
            await self._cancel_task_on_owner_loop(task)
        self._task = None
        self._loop = None
        if broadcast:
            self.publish({"type": "interrupted", "data": {"message": "Session run cancelled"}})

    async def _cancel_task_on_owner_loop(self, task: asyncio.Task) -> None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _run(self, run_factory: RunFactory) -> None:
        current_task = asyncio.current_task()
        token = set_worker_event_callback(self.publish)
        try:
            async for event in run_factory():
                self.publish(event)
            self.publish({"type": "done"})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.publish({"type": "error", "data": categorize_exception(exc)})
            self.publish({"type": "done"})
        finally:
            reset_worker_event_callback(token)
            if self._task is current_task:
                self._task = None
                self._loop = None


_session_runtimes: Dict[str, SessionRuntime] = {}


def get_session_runtime(session_id: str) -> SessionRuntime:
    runtime = _session_runtimes.get(session_id)
    if runtime is None or runtime.is_deleted:
        runtime = SessionRuntime(session_id)
        _session_runtimes[session_id] = runtime
    return runtime


async def terminate_session_runtime(session_id: str, session: Optional[AgentSession] = None) -> bool:
    runtime = _session_runtimes.pop(session_id, None)
    if runtime is None:
        return False
    await runtime.terminate(session)
    return True
