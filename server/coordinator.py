"""Authorize, commit and publish gameplay under the room's lock."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from poker.engine import Player, apply_action
from poker.rooms import Room, RoomManager

from .commands import ActionCommand, Command
from .connections import Connection, ConnectionRegistry
from .views import player_view

REPLAY_CAPACITY = 256
AdmissionResult = TypeVar("AdmissionResult")


@dataclass(frozen=True)
class Acknowledgment:
    hand_id: int
    action_id: str
    outcome_revision: int
    accepted: bool
    error_code: str | None

    def message(self) -> dict[str, object]:
        return {
            "type": "action_ack",
            "hand_id": self.hand_id,
            "action_id": self.action_id,
            "outcome_revision": self.outcome_revision,
            "accepted": self.accepted,
            "error_code": self.error_code,
        }


class GameCoordinator:
    def __init__(self, rooms: RoomManager, *, replay_capacity: int = REPLAY_CAPACITY):
        self._rooms = rooms
        self._connections = ConnectionRegistry()
        self._capacity = replay_capacity
        self._replays: dict[
            tuple[Player, int], dict[str, tuple[Command, Acknowledgment]]
        ] = {}

    def admit(
        self, join: Callable[[str], AdmissionResult], room_code: str
    ) -> AdmissionResult:
        with self._rooms.synchronized():
            admission = join(room_code)
            room = self._rooms.snapshot()
            assert room is not None and room.hand is not None
            self._publish_game(room)
            self._connections.publish_lobby(table_ready=True)
            return admission

    def attach(self, token: str, connection: Connection) -> Player | None:
        with self._rooms.synchronized():
            view = self._rooms.authenticate(token)
            if view is None:
                return None
            self._connections.attach(view.seat, connection)
            room = self._rooms.snapshot()
            assert room is not None
            if connection.gameplay:
                connection.offer(player_view(room, view.seat, room.revision))
            self._connections.publish_lobby(room.status == "ready")
            return view.seat

    def detach(self, seat: Player, connection: Connection) -> None:
        with self._rooms.synchronized():
            if self._connections.detach_if_current(seat, connection):
                room = self._rooms.snapshot()
                assert room is not None
                self._connections.publish_lobby(room.status == "ready")

    def reply(self, seat: Player, connection: Connection, payload: dict[str, object]):
        with self._rooms.synchronized():
            if self._connections.is_current(seat, connection):
                connection.offer(payload)

    def snapshot(self, seat: Player, connection: Connection) -> None:
        with self._rooms.synchronized():
            if self._connections.is_current(seat, connection):
                room = self._rooms.snapshot()
                assert room is not None
                connection.offer(player_view(room, seat, room.revision))

    def _publish_game(self, room: Room) -> None:
        for seat, connection in self._connections.active():
            if connection.gameplay:
                connection.offer(player_view(room, seat, room.revision))

    def submit(self, seat: Player, connection: Connection, command: Command) -> None:
        with self._rooms.synchronized():
            if (
                not self._connections.is_current(seat, connection)
                or not connection.gameplay
            ):
                return
            room = self._rooms.snapshot()
            assert room is not None
            updated = room
            hand = room.hand
            key = (seat, command.hand_id)
            cache = self._replays.get(key, {})
            previous = cache.get(command.action_id)

            if previous is not None and previous[0] == command:
                connection.offer(previous[1].message())
                return

            eligible = (
                previous is None
                and hand is not None
                and command.hand_id == hand.hand_number
                and len(cache) < self._capacity
            )
            if previous is not None:
                error = "REPLAY_CONFLICT"
            elif hand is None:
                error = "NOT_READY"
            elif command.hand_id != hand.hand_number:
                error = "WRONG_HAND"
            elif not eligible:
                error = "REPLAY_CAPACITY"
            elif command.expected_revision != room.revision:
                error = "STALE_REVISION"
            else:
                updated, error = self._apply(room, seat, command)

            outcome = Acknowledgment(
                command.hand_id,
                command.action_id,
                updated.revision,
                error is None,
                error,
            )
            if eligible:
                cache[command.action_id] = command, outcome
                self._replays[key] = cache
                if (
                    updated.hand is not None
                    and updated.hand.hand_number != command.hand_id
                ):
                    self._prune(updated.hand.hand_number)

            connection.offer(outcome.message())
            if updated is not room:
                self._publish_game(updated)
            elif error in {"WRONG_HAND", "STALE_REVISION"}:
                connection.offer(player_view(room, seat, room.revision))

    def _apply(
        self, room: Room, seat: Player, command: Command
    ) -> tuple[Room, str | None]:
        hand = room.hand
        assert hand is not None
        action = command.action if isinstance(command, ActionCommand) else "ready"
        result = apply_action(hand, seat, action)
        if result.accepted:
            return self._rooms.commit_hand(room, result.state), None
        if hand.match_winner is not None:
            return room, "MATCH_COMPLETE"
        if isinstance(command, ActionCommand):
            if hand.phase in {"showdown", "finished"}:
                return room, "HAND_COMPLETE"
            if hand.actor != seat:
                return room, "WRONG_TURN"
        return room, "ILLEGAL_ACTION"

    def _prune(self, hand_number: int) -> None:
        self._replays = {
            key: entries
            for key, entries in self._replays.items()
            if key[1] >= hand_number - 1
        }
