from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import TYPE_CHECKING, Optional

from app.gateway.envelope import MessageEnvelope
from app.gateway.session_keys import build_session_id
from app.gateway.translators.base import Translator

if TYPE_CHECKING:
    from app.connectors.base import PlatformConnector

logger = logging.getLogger(__name__)


DEFAULT_TIMEOUT_S = 300


async def dispatch(
    connector: "PlatformConnector",
    envelope: MessageEnvelope,
    translator: Translator,
    *,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> str:
    """Drive one user message → agent turn → translator output.

    Steps:
        1. Resolve target agent / model / role from the connector config.
        2. Build a deterministic session_id including thread/reply context.
        3. Cancel any in-flight run on the same session (latest message wins).
        4. Start the SessionRuntime task with ``session.run(prompt)``.
        5. Subscribe to the runtime's event queue and feed events to the
           translator until ``done`` or ``error`` is published.

    Returns the session_id used.
    """
    from app.agent import get_or_create_session
    from app.session_runtime import cancel_session_runtime, get_session_runtime

    agent_type, role_id, model_id = connector.resolve_agent_target()
    session_id = build_session_id(envelope, connector.name, agent_type)

    prompt = envelope.context_prefix() + envelope.text

    # Latest-message-wins: drop any prior in-flight run on this session
    # so the user does not see two interleaved replies.
    await cancel_session_runtime(session_id, broadcast=False)

    session = get_or_create_session(
        session_id, model_id, role_id=role_id, agent_type=agent_type,
    )

    runtime = get_session_runtime(session_id)
    queue: asyncio.Queue = runtime.subscribe()

    def _factory():
        return session.run(prompt, None)

    consumer_task: Optional[asyncio.Task] = None
    try:
        await runtime.start(session, _factory)

        async def _consume() -> None:
            while True:
                event = await queue.get()
                try:
                    await translator.handle_event(event)
                except Exception:
                    logger.exception(
                        "[gateway] translator failed for session=%s event=%s",
                        session_id, event.get("type"),
                    )
                if event.get("type") in {"done", "error"}:
                    return

        consumer_task = asyncio.create_task(_consume())
        connector._running_tasks[session_id] = consumer_task

        await asyncio.wait_for(consumer_task, timeout=timeout_s)
        return session_id
    except asyncio.TimeoutError:
        logger.warning("[gateway] dispatch timeout session=%s", session_id)
        await cancel_session_runtime(session_id, broadcast=True)
        with suppress(Exception):
            await translator.on_error(TimeoutError(f"Agent run exceeded {timeout_s}s"))
        return session_id
    except asyncio.CancelledError:
        with suppress(Exception):
            await translator.on_error(asyncio.CancelledError("superseded by new message"))
        raise
    except Exception as exc:
        logger.exception("[gateway] dispatch failed session=%s", session_id)
        with suppress(Exception):
            await translator.on_error(exc)
        return session_id
    finally:
        runtime.unsubscribe(queue)
        if consumer_task is not None and connector._running_tasks.get(session_id) is consumer_task:
            connector._running_tasks.pop(session_id, None)
