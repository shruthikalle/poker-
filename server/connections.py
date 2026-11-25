"""Track the current WebSocket for each seat without exposing session tokens."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from fastapi import WebSocket, WebSocketDisconnect

from .sessions import Seat


@dataclass
class Connection:
    websocket: WebSocket
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, payload: dict[str, object]) -> None:
        async with self.send_lock:
            await self.websocket.send_json(payload)


class ConnectionRegistry:
    """One active socket per seat; old socket cleanup cannot remove a replacement."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._current: dict[Seat, Connection] = {}

    async def attach(self, seat: Seat, websocket: WebSocket) -> Connection | None:
        async with self._lock:
            previous = self._current.get(seat)
            self._current[seat] = Connection(websocket)
            return previous

    async def detach_if_current(self, seat: Seat, websocket: WebSocket) -> bool:
        async with self._lock:
            current = self._current.get(seat)
            if current is None or current.websocket is not websocket:
                return False
            del self._current[seat]
            return True

    async def connected(self) -> dict[Seat, bool]:
        async with self._lock:
            return {seat: seat in self._current for seat in ("A", "B")}

    async def broadcast_lobby(self, table_ready: bool) -> None:
        async with self._lock:
            current = dict(self._current)
            connected = {seat: seat in current for seat in ("A", "B")}
        for seat, connection in current.items():
            # No engine object or token is ever included in a lobby snapshot.
            try:
                await connection.send(
                    LobbySnapshot(
                        your_seat=seat,
                        table_ready=table_ready,
                        connected=connected,
                    ).as_message()
                )
            except (RuntimeError, OSError, WebSocketDisconnect):
                await self.detach_if_current(seat, connection.websocket)


@dataclass(frozen=True)
class LobbySnapshot:
    """Typed, allowlisted server snapshot before game integration."""

    your_seat: Seat
    table_ready: bool
    connected: dict[Seat, bool]

    def as_message(self) -> dict[str, object]:
        return {
            "type": "lobby",
            "your_seat": self.your_seat,
            "table_ready": self.table_ready,
            "connected": {"A": self.connected["A"], "B": self.connected["B"]},
        }
