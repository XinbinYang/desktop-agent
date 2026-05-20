from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any, AsyncIterator, Callable, Dict, Optional, Set

from app.agent import AgentSession
from app.errors import categorize_exception
from app.tools.worker_tool import reset_worker_event_callback, set_worker_event_callback


logger = logging.getLogger(__name__)


RunFactory = Callable[[], AsyncIterator[Dict[str, Any]]]


class SessionRuntime:
    """Owns the live background run for one chat session.

    WebSocket connections are transient UI transports. The agent run belongs
    to the session itself so a renderer reload, HMR reconnect, pane remount, or
    short network break cannot cancel the underlying task.

    Lifecycle (per turn):
      - start() creates `_task` (running agent.run()) and a fresh
        `_turn_completed` event.
      - When `_run()` publishes the `done` event (either after a
        completion-boundary `run_completed`, or via fallback), it also signals
        `_turn_completed`. This is the public "this turn produced its final
        answer" moment.
      - The trailing work in agent.run() (close_coding_run, async _save) may
        still take tens to hundreds of milliseconds after `done`. To avoid
        making the next user message wait on that, wait_until_idle() returns
        as soon as `_turn_completed` is set.
      - start() of a new turn DETACHES (does not cancel) the previous task if
        its `_turn_completed` is already set, so the trailing _save_async can
        finish in background. AgentSession._build_save_payload shallow-copies
        mutable state so concurrent mutation by the new turn is safe.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._subscribers: Set[asyncio.Queue[Dict[str, Any]]] = set()
        self._lock = asyncio.Lock()
        self._deleted = False
        self._accepts_task_guidance = False
        self._turn_completed: Optional[asyncio.Event] = None
        self._detached_tasks: Set[asyncio.Task] = set()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def accepts_task_guidance(self) -> bool:
        return self.is_running and self._accepts_task_guidance

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
            self._accepts_task_guidance = True
            self._turn_completed = asyncio.Event()
            self._task = asyncio.create_task(self._run(session, run_factory))

    async def cancel(self, session: Optional[AgentSession] = None, *, broadcast: bool = True) -> None:
        async with self._lock:
            await self._cancel_locked(session, broadcast=broadcast, allow_detach=False)

    async def terminate(self, session: Optional[AgentSession] = None) -> None:
        async with self._lock:
            self._deleted = True
            await self._cancel_locked(session, broadcast=False, allow_detach=False)
            self._subscribers.clear()

    async def _cancel_locked(
        self,
        session: Optional[AgentSession],
        *,
        broadcast: bool,
        allow_detach: bool = True,
    ) -> None:
        task = self._task
        turn_completed = self._turn_completed
        # If the previous turn has already published `done`, its remaining work
        # (close_coding_run + _save_async) is post-answer cleanup. Detach rather
        # than cancel so the disk write completes safely; the new turn can
        # start immediately. AgentSession._build_save_payload snapshots mutable
        # state, so concurrent mutation by the new turn is safe.
        # Explicit cancel/terminate disables this so user-initiated stops are
        # honored even mid-save.
        if (
            allow_detach
            and task is not None
            and not task.done()
            and turn_completed is not None
            and turn_completed.is_set()
            and not broadcast
        ):
            self._detached_tasks.add(task)
            task.add_done_callback(self._on_detached_done)
            self._task = None
            self._loop = None
            self._accepts_task_guidance = False
            return

        if session is not None:
            session.cancel()
        if task is None or task.done():
            self._task = None
            self._loop = None
            self._accepts_task_guidance = False
            if turn_completed is not None:
                turn_completed.set()
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
        self._accepts_task_guidance = False
        if turn_completed is not None:
            turn_completed.set()
        if broadcast:
            self.publish({"type": "interrupted", "data": {"message": "Session run cancelled"}})

    def _on_detached_done(self, task: asyncio.Task) -> None:
        self._detached_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.exception("Detached session task failed: %s", exc, exc_info=exc)

    async def _cancel_task_on_owner_loop(self, task: asyncio.Task) -> None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def wait_until_idle(self) -> None:
        # Returns as soon as the agent has produced its final answer for the
        # current turn (the `done` event has been published). Trailing work
        # like _save_async may continue in background — the new turn can
        # safely run concurrently because state mutations are snapshotted.
        turn_completed = self._turn_completed
        task = self._task
        if task is None or task.done():
            return
        if turn_completed is not None:
            with suppress(asyncio.CancelledError):
                await turn_completed.wait()
            return
        with suppress(asyncio.CancelledError):
            await asyncio.shield(task)

    @staticmethod
    def _is_terminal_event(event: Dict[str, Any]) -> bool:
        etype = event.get("type")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if etype == "status":
            return data.get("status") in {
                "completed",
                "max_iterations_reached",
                "cancelled",
                "failed",
            }
        if etype == "run_completed":
            return data.get("status") in {
                "completed",
                "max_iterations_reached",
                "cancelled",
                "failed",
            }
        if etype == "error":
            return True
        return False

    @staticmethod
    def _is_completion_boundary(event: Dict[str, Any]) -> bool:
        etype = event.get("type")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        return etype == "run_completed" and data.get("status") in {
            "completed",
            "max_iterations_reached",
            "cancelled",
            "failed",
        }

    def _schedule_personal_heartbeat(self, session: AgentSession) -> None:
        if session.agent_type != "personal":
            return

        async def _run_heartbeat() -> None:
            try:
                from app.agents.heartbeat import HeartbeatEngine

                await HeartbeatEngine.on_session_end(
                    session.heartbeat_transcript_messages(),
                    session.session_id,
                )
            except Exception:
                pass

        asyncio.create_task(_run_heartbeat())

    def _signal_turn_completed(self) -> None:
        ev = self._turn_completed
        if ev is not None and not ev.is_set():
            ev.set()

    async def _run(self, session: AgentSession, run_factory: RunFactory) -> None:
        current_task = asyncio.current_task()
        token = set_worker_event_callback(self.publish)
        done_published = False
        try:
            async for event in run_factory():
                if self._is_terminal_event(event):
                    self._accepts_task_guidance = False
                self.publish(event)
                if not done_published and self._is_completion_boundary(event):
                    done_published = True
                    self.publish({"type": "done"})
                    self._signal_turn_completed()
                    self._schedule_personal_heartbeat(session)
                    await asyncio.sleep(0)
            self._accepts_task_guidance = False
            if not done_published:
                self.publish({"type": "done"})
                self._signal_turn_completed()
                self._schedule_personal_heartbeat(session)
        except asyncio.CancelledError:
            self._signal_turn_completed()
            raise
        except Exception as exc:
            self._accepts_task_guidance = False
            if not done_published:
                self.publish({"type": "error", "data": categorize_exception(exc)})
                self.publish({"type": "done"})
            self._signal_turn_completed()
        finally:
            reset_worker_event_callback(token)
            self._signal_turn_completed()
            if self._task is current_task:
                self._task = None
                self._loop = None
                self._accepts_task_guidance = False


_session_runtimes: Dict[str, SessionRuntime] = {}


def get_session_runtime(session_id: str) -> SessionRuntime:
    runtime = _session_runtimes.get(session_id)
    if runtime is None or runtime.is_deleted:
        runtime = SessionRuntime(session_id)
        _session_runtimes[session_id] = runtime
    return runtime


def session_runtime_status(session_id: str) -> Dict[str, Any]:
    runtime = _session_runtimes.get(session_id)
    return {
        "session_id": session_id,
        "is_running": bool(runtime and runtime.is_running),
        "accepts_task_guidance": bool(runtime and runtime.accepts_task_guidance),
        "is_deleted": bool(runtime and runtime.is_deleted),
    }


async def cancel_session_runtime(
    session_id: str,
    session: Optional[AgentSession] = None,
    *,
    broadcast: bool = True,
) -> bool:
    runtime = _session_runtimes.get(session_id)
    if runtime is None:
        return False
    was_running = runtime.is_running
    await runtime.cancel(session, broadcast=broadcast)
    return was_running


async def terminate_session_runtime(session_id: str, session: Optional[AgentSession] = None) -> bool:
    runtime = _session_runtimes.pop(session_id, None)
    if runtime is None:
        return False
    await runtime.terminate(session)
    return True
