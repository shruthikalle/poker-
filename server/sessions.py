"""Adapt the lobby session contract to the authoritative room manager."""

from collections.abc import Callable

from poker.engine import Player as Seat
from poker.rooms import RoomAlreadyExists, RoomFull, RoomManager, RoomNotFound


class SessionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SessionStore:
    """Expose the lobby's seat and error formats over the shared room."""

    def __init__(
        self,
        code_factory: Callable[[], str] | None = None,
        token_factory: Callable[[], str] | None = None,
        *,
        manager: RoomManager | None = None,
    ) -> None:
        self._manager = (
            manager
            if manager is not None
            else RoomManager(code_factory=code_factory, token_factory=token_factory)
        )

    def create(self) -> tuple[str, str]:
        try:
            admission = self._manager.create(bet_unit=10)
        except RoomAlreadyExists as exc:
            raise SessionError("TABLE_EXISTS", "A table already exists") from exc
        return admission.room_code, admission.session_token

    def join(self, room_code: str) -> str:
        try:
            return self._manager.join(room_code).session_token
        except RoomNotFound as exc:
            raise SessionError("INVALID_CODE", "Table code not found") from exc
        except RoomFull as exc:
            raise SessionError("TABLE_FULL", "Table already has two players") from exc

    def seat_for_token(self, token: str) -> tuple[Seat, bool]:
        view = self._manager.authenticate(token)
        if view is None:
            raise SessionError("UNAUTHORIZED", "Invalid session token")
        return view.seat, view.status == "ready"

    def table_ready(self) -> bool:
        room = self._manager.snapshot()
        return room is not None and room.status == "ready"
