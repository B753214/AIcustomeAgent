"""SSE comment heartbeats while waiting for the next business event."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import anyio

HEARTBEAT = ": heartbeat\n\n"


async def with_sse_heartbeat(
    events: AsyncIterator[str], *, interval: float = 15.0,
) -> AsyncIterator[str]:
    """Keep one pending read alive across heartbeats; close it on disconnect.

    This limits idle gaps, not the total run duration. Heartbeats are transport
    comments, so they do not become RunEvents or enter event persistence.
    """
    if interval <= 0:
        raise ValueError("heartbeat interval must be positive")
    iterator = events.__aiter__()
    pending: asyncio.Task[str] | None = None
    try:
        # Flush response headers immediately, including during route/model setup.
        yield HEARTBEAT
        while True:
            if pending is None:
                pending = asyncio.create_task(anext(iterator))
            ready, _ = await asyncio.wait({pending}, timeout=interval)
            if not ready:
                yield HEARTBEAT
                continue
            try:
                event = pending.result()
            except StopAsyncIteration:
                return
            pending = None
            yield event
    finally:
        # Starlette may cancel the response inside an AnyIO cancel scope. Shield
        # cleanup so the in-flight read and generator finally blocks can finish.
        with anyio.CancelScope(shield=True):
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            close = getattr(iterator, "aclose", None)
            if close is not None:
                await close()
