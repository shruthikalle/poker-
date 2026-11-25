"""Per-seat socket ownership and bounded FIFO delivery."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from anyio import create_task_group
from fastapi import WebSocket, WebSocketDisconnect

from .sessions import Seat

QUEUE_CAPACITY = 32


@dataclass(eq=False)
class Connection:
    websocket: WebSocket
    gameplay: bool
    queue: asyncio.Queue[dict[str, object]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=QUEUE_CAPACITY)
    )
    closing: asyncio.Event = field(default_factory=asyncio.Event)
    close_code: int = 1000

    def request_close(self, code: int) -> None:
        if not self.closing.is_set():
            self.close_code = code
            self.closing.set()

    def offer(self, payload: dict[str, object]) -> None:
        if self.closing.is_set():
            return
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            self.request_close(1013)

    async def _write(self) -> None:
        while True:
            await self.websocket.send_json(await self.queue.get())

    async def run(self, read: Callable[[], Awaitable[None]]) -> None:
        async with create_task_group() as group:

            async def end_when_done(operation: Callable[[], Awaitable[None]]) -> None:
                try:
                    await operation()
                except (WebSocketDisconnect, OSError):
                    pass
                group.cancel_scope.cancel()

            async def wait_for_close() -> None:
                await self.closing.wait()

            group.start_soon(end_when_done, read)
            group.start_soon(end_when_done, self._write)
            group.start_soon(end_when_done, wait_for_close)

    async def finish_close(self) -> None:
        if self.closing.is_set():
            try:
                await asyncio.wait_for(self.websocket.close(code=self.close_code), 1)
            except (TimeoutError, RuntimeError, OSError, WebSocketDisconnect):
                pass


class ConnectionRegistry:
    """Access from the event loop under the room synchronization boundary."""

    def __init__(self) -> None:
        self._current: dict[Seat, Connection] = {}

    def attach(self, seat: Seat, connection: Connection) -> None:
        previous = self._current.get(seat)
        self._current[seat] = connection
        if previous is not None:
            previous.request_close(4000)

    def is_current(self, seat: Seat, connection: Connection) -> bool:
        return self._current.get(seat) is connection and not connection.closing.is_set()

    def detach_if_current(self, seat: Seat, connection: Connection) -> bool:
        if self._current.get(seat) is not connection:
            return False
        del self._current[seat]
        return True

    def active(self) -> tuple[tuple[Seat, Connection], ...]:
        return tuple(
            (seat, connection)
            for seat, connection in self._current.items()
            if not connection.closing.is_set()
        )

    def publish_lobby(self, table_ready: bool) -> None:
        active = self.active()
        connected = dict(active)
        for seat, connection in active:
            if not connection.gameplay:
                connection.offer(
                    {
                        "type": "lobby",
                        "your_seat": seat,
                        "table_ready": table_ready,
                        "connected": {"A": "A" in connected, "B": "B" in connected},
                    }
                )
