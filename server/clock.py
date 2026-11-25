"""Monotonic time and deadline waits for the room scheduler."""

import asyncio
from time import monotonic_ns
from typing import Protocol

from anyio import move_on_after

SECOND = 1_000_000_000


class Clock(Protocol):
    def now_ns(self) -> int: ...

    async def wait(self, changed: asyncio.Event, deadline: int | None) -> None: ...


class MonotonicClock:
    def now_ns(self) -> int:
        return monotonic_ns()

    async def wait(self, changed: asyncio.Event, deadline: int | None) -> None:
        if deadline is None:
            await changed.wait()
        else:
            with move_on_after(max(0, deadline - self.now_ns()) / SECOND):
                await changed.wait()
