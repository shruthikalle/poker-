"""Table admission and seat identity; no game state lives here yet."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal

Seat = Literal["A", "B"]


class SessionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Table:
    room_code: str
    tokens: dict[Seat, str] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return "A" in self.tokens and "B" in self.tokens


class SessionStore:
    """One in-memory table with atomic create and join operations."""

    def __init__(
        self,
        code_factory: Callable[[], str] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._lock = Lock()
        self._table: Table | None = None
        self._code_factory = code_factory or (lambda: secrets.token_hex(4).upper())
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))

    def create(self) -> tuple[str, str]:
        with self._lock:
            if self._table is not None:
                raise SessionError("TABLE_EXISTS", "A table already exists")
            code = self._code_factory()
            token = self._token_factory()
            self._table = Table(code, {"A": token})
            return code, token

    def join(self, room_code: str) -> str:
        with self._lock:
            table = self._table
            if table is None or not secrets.compare_digest(table.room_code, room_code):
                raise SessionError("INVALID_CODE", "Table code not found")
            if "B" in table.tokens:
                raise SessionError("TABLE_FULL", "Table already has two players")
            token = self._token_factory()
            if secrets.compare_digest(table.tokens["A"], token):
                raise RuntimeError("token generator returned a duplicate token")
            table.tokens["B"] = token
            return token

    def seat_for_token(self, token: str) -> tuple[Seat, bool]:
        with self._lock:
            table = self._table
            if table is not None:
                for seat, issued in table.tokens.items():
                    if secrets.compare_digest(issued, token):
                        return seat, table.ready
            raise SessionError("UNAUTHORIZED", "Invalid session token")
