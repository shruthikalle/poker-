"""In-memory room admission independent of the network transport."""

from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from hashlib import sha256
from hmac import digest
from secrets import compare_digest, token_bytes, token_urlsafe
from threading import RLock
from typing import Literal

from .engine import GameState, Player, Ruleset, new_game

RoomStatus = Literal["waiting", "ready"]


class InvalidBetUnit(ValueError):
    pass


class RoomAlreadyExists(Exception):
    pass


class RoomNotFound(Exception):
    pass


class RoomFull(Exception):
    pass


class AdmissionConflict(Exception):
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
    revision: int = 0
    generation: int = 0

    @property
    def status(self) -> RoomStatus:
        return "ready" if self.seat_b_token is not None else "waiting"


class RoomManager:
    """Own the process's single active room for one running app."""

    def __init__(
        self,
        *,
        code_factory: Callable[[], str] | None = None,
        token_factory: Callable[[], str] | None = None,
        deck: tuple[str, ...] | None = None,
        ruleset: Ruleset = "pdf",
    ) -> None:
        if ruleset not in ("legacy", "pdf"):
            raise ValueError("unknown ruleset")
        self._code_factory = code_factory or (lambda: token_urlsafe(9))
        self._token_factory = token_factory
        self._secret = token_bytes(32)
        self._generation = 0
        self._deck = deck
        self._ruleset = ruleset
        self._lock = RLock()
        self._room: Room | None = None
        self._admissions: list[tuple[bytes, tuple[str, int | str], Admission]] = []

    @property
    def ruleset(self) -> Ruleset:
        return self._ruleset

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def _tag(self, purpose: str, value: str) -> str:
        return digest(self._secret, f"{purpose}:{value}".encode(), "sha256").hex()[:32]

    def _new_token(self) -> str:
        if self._token_factory:
            provided = self._token_factory()
            if self._generation == 0:
                return provided
            nonce = sha256(provided.encode()).digest()[:16]
        else:
            nonce = token_bytes(16)
        payload = self._generation.to_bytes(4, "big") + nonce
        token = payload + digest(self._secret, b"seat:" + payload, "sha256")[:12]
        return urlsafe_b64encode(token).decode().rstrip("=")

    def is_retired_token(self, token: str) -> bool:
        if self.generation == 0 or len(token) != 43 or not token.isascii():
            return False
        try:
            raw = urlsafe_b64decode(token + "=")
        except Base64Error:
            return False
        if len(raw) != 32 or urlsafe_b64encode(raw).decode().rstrip("=") != token:
            return False
        payload, signature = raw[:20], raw[20:]
        return int.from_bytes(payload[:4], "big") < self.generation and compare_digest(
            signature, digest(self._secret, b"seat:" + payload, "sha256")[:12]
        )

    def admit_once(
        self,
        identifier: str | None,
        request: tuple[str, int | str],
        allocate: Callable[[], Admission],
    ) -> Admission:
        """Retain only successful keyed admissions for this room's lifetime."""
        if identifier is None:
            return allocate()
        digest = sha256(identifier.encode("ascii")).digest()
        with self._lock:
            for previous, intent, admission in self._admissions:
                if compare_digest(digest, previous):
                    if intent != request:
                        raise AdmissionConflict
                    return admission
            admission = allocate()
            # Allocation itself enforces the two-seat limit. Failed allocation
            # leaves the replay records untouched.
            self._admissions.append((digest, request, admission))
            return admission

    def create(self, bet_unit: object) -> Admission:
        if self._ruleset == "pdf" and bet_unit != 10:
            raise InvalidBetUnit("PDF rules require a fixed 10-chip big blind")
        if type(bet_unit) is not int or not 2 <= bet_unit <= 20 or bet_unit % 2:
            raise InvalidBetUnit("bet unit must be an even integer from 2 to 20")

        with self._lock:
            if self._room is not None:
                raise RoomAlreadyExists("an active room already exists")

            code = self._code_factory()
            if self._generation:
                code = f"{code}_{self._tag('code', str(self._generation))}"
            room = Room(code, bet_unit, self._new_token(), generation=self._generation)
            self._room = room
            return Admission(room.code, "A", room.seat_a_token, bet_unit, room.status)

    def join(self, room_code: object) -> Admission:
        with self._lock:
            room = self._room
            if (
                room is None
                or type(room_code) is not str
                or not room_code.isascii()
                or not compare_digest(room.code, room_code)
            ):
                raise RoomNotFound("room not found")
            if room.seat_b_token is not None:
                raise RoomFull("room is full")

            for _ in range(8):
                token = self._new_token()
                if token != room.seat_a_token:
                    break
            else:
                raise RuntimeError("could not generate a unique session token")

            joined = replace(
                room,
                seat_b_token=token,
                hand=new_game(
                    bet_unit=room.bet_unit, deck=self._deck, ruleset=self._ruleset
                ),
                revision=1,
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

    @contextmanager
    def synchronized(self) -> Iterator[None]:
        """Serialize compound room operations without awaiting under the lock."""
        with self._lock:
            yield

    def commit_hand(self, current: Room, hand: GameState) -> Room:
        """Commit an engine transition inside the same room transaction."""
        with self._lock:
            if current is not self._room or current.hand is None:
                raise RuntimeError("room transition requires the current dealt hand")
            if hand != current.hand:
                self._room = replace(current, hand=hand, revision=current.revision + 1)
            return self._room

    def retire(self, current: Room) -> None:
        """Discard room and admission authority inside the owning transaction."""
        with self._lock:
            if current is not self._room:
                raise RuntimeError("room retirement requires the current room")
            self._room = None
            self._admissions.clear()
            self._generation += 1

    def snapshot(self) -> Room | None:
        """Return the immutable server-side state for inspection."""
        with self._lock:
            return self._room
