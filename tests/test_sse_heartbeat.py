"""Heartbeat scheduling and producer cleanup without model/database dependencies."""
import asyncio

import anyio
import pytest

from app.services.sse import HEARTBEAT, with_sse_heartbeat


@pytest.mark.asyncio
async def test_heartbeats_keep_the_same_pending_read_alive():
    release = asyncio.Event()
    started = asyncio.Event()
    reads = 0
    closed = False

    async def source():
        nonlocal reads, closed
        try:
            reads += 1
            started.set()
            await release.wait()
            yield 'data: {"type":"run.completed"}\n\n'
        finally:
            closed = True

    stream = with_sse_heartbeat(source(), interval=0.01)
    assert await anext(stream) == HEARTBEAT
    for _ in range(2):
        assert await asyncio.wait_for(anext(stream), 1) == HEARTBEAT
    assert started.is_set()
    assert reads == 1
    assert not closed
    release.set()
    assert await asyncio.wait_for(anext(stream), 1) == 'data: {"type":"run.completed"}\n\n'
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert closed


@pytest.mark.asyncio
async def test_business_events_keep_order_and_end_without_extra_heartbeats():
    async def source():
        yield 'data: {"content":"A"}\n\n'
        yield 'data: {"content":"B"}\n\n'

    result = [event async for event in with_sse_heartbeat(source(), interval=1)]
    assert result == [HEARTBEAT, 'data: {"content":"A"}\n\n', 'data: {"content":"B"}\n\n']


@pytest.mark.asyncio
async def test_closing_after_heartbeat_cancels_inflight_producer():
    closed = asyncio.Event()

    async def source():
        try:
            await asyncio.Event().wait()
            yield "unreachable"
        finally:
            closed.set()

    stream = with_sse_heartbeat(source(), interval=0.01)
    assert await anext(stream) == HEARTBEAT
    assert await asyncio.wait_for(anext(stream), 1) == HEARTBEAT
    await asyncio.wait_for(stream.aclose(), 1)
    assert closed.is_set()


@pytest.mark.asyncio
async def test_response_task_cancellation_cleans_up_pending_read():
    started = asyncio.Event()
    closed = asyncio.Event()

    async def source():
        try:
            started.set()
            await asyncio.Event().wait()
            yield "unreachable"
        finally:
            closed.set()

    async def consume():
        async for _ in with_sse_heartbeat(source(), interval=10):
            pass

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


@pytest.mark.asyncio
async def test_anyio_disconnect_scope_allows_cleanup():
    started = anyio.Event()
    closed = anyio.Event()

    async def source():
        try:
            started.set()
            await anyio.sleep_forever()
            yield "unreachable"
        finally:
            # Cleanup itself must be allowed to await inside the cancelled scope.
            await anyio.sleep(0)
            closed.set()

    async def consume():
        async for _ in with_sse_heartbeat(source(), interval=10):
            pass

    async with anyio.create_task_group() as group:
        group.start_soon(consume)
        await started.wait()
        group.cancel_scope.cancel()
    assert closed.is_set()


@pytest.mark.asyncio
async def test_source_failure_propagates():
    async def source():
        raise RuntimeError("producer failed")
        yield "unreachable"

    stream = with_sse_heartbeat(source())
    assert await anext(stream) == HEARTBEAT
    with pytest.raises(RuntimeError, match="producer failed"):
        await anext(stream)


@pytest.mark.asyncio
async def test_nonpositive_interval_rejected():
    async def source():
        yield "event"

    with pytest.raises(ValueError, match="positive"):
        await anext(with_sse_heartbeat(source(), interval=0))
