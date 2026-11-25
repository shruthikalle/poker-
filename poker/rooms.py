"""In-memory room admission independent of the network transport."""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from secrets import compare_digest, token_urlsafe
from threading import Lock
from typing import Literal

from .engine import GameState, Player, new_game

RoomStatus = Literal["waiting", "ready"]


class InvalidBetUnit(ValueError):
    pass


class RoomAlreadyExists(Exception):
    pass


class RoomNotFound(Exception):
    pass


class RoomFull(Exception):
    pass


@dataclass(frozen=True)
class Admission:
    room_code: str = field(repr=False)
    seat: Player
    session_token: str = field(repr=False)
    bet_unit: int
    status: RoomStatus


@dataclass(frozen=True)
class RoomView:
    seat: Player
    bet_unit: int
    status: RoomStatus


@dataclass(frozen=True)
class Room:
    code: str = field(repr=False)
    bet_unit: int
    seat_a_token: str = field(repr=False)
    seat_b_token: str | None = field(default=None, repr=False)
    hand: GameState | None = field(default=None, repr=False)

    @property
    def status(self) -> RoomStatus:
        return "ready" if self.seat_b_token is not None else "waiting"


class RoomManager:
    """Own the process's single active room for one running app."""

    def __init__(
        self,
        *,
        code_factory: Callable[[], str] = lambda: token_urlsafe(9),
        token_factory: Callable[[], str] = lambda: token_urlsafe(32),
    ) -> None:
        self._code_factory = code_factory
        self._token_factory = token_factory
        self._lock = Lock()
        self._room: Room | None = None

    def create(self, bet_unit: object) -> Admission:
        if type(bet_unit) is not int or not 2 <= bet_unit <= 20 or bet_unit % 2:
            raise InvalidBetUnit("bet unit must be an even integer from 2 to 20")

        with self._lock:
            if self._room is not None:
                raise RoomAlreadyExists("an active room already exists")

            room = Room(self._code_factory(), bet_unit, self._token_factory())
            self._room = room
            return Admission(room.code, "A", room.seat_a_token, bet_unit, room.status)

    def join(self, room_code: object) -> Admission:
        with self._lock:
            room = self._room
            if room is None or type(room_code) is not str or room_code != room.code:
                raise RoomNotFound("room not found")
            if room.seat_b_token is not None:
                raise RoomFull("room is full")

            for _ in range(8):
                token = self._token_factory()
                if token != room.seat_a_token:
                    break
            else:
                raise RuntimeError("could not generate a unique session token")

            joined = replace(
                room, seat_b_token=token, hand=new_game(bet_unit=room.bet_unit)
            )
            self._room = joined
            return Admission(joined.code, "B", token, joined.bet_unit, joined.status)

    def authenticate(self, token: str) -> RoomView | None:
        if not token or not token.isascii():
            return None
        with self._lock:
            room = self._room
            if room is None:
                return None
            if compare_digest(token, room.seat_a_token):
                return RoomView("A", room.bet_unit, room.status)
            if room.seat_b_token is not None and compare_digest(
                token, room.seat_b_token
            ):
                return RoomView("B", room.bet_unit, room.status)
            return None

    def snapshot(self) -> Room | None:
        """Return the immutable server-side state for inspection."""
        with self._lock:
            return self._room
