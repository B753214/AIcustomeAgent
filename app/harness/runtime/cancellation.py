from __future__ import annotations

import asyncio


class CancellationToken:
    """一次 Run 的取消信号；客户端断开或主动取消时 set。"""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()
