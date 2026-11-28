"""Authorize, commit and publish gameplay under the room's lock."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from logging import getLogger
from typing import TypeVar

from poker.engine import Player, apply_action, legal_actions
from poker.rooms import Room, RoomManager

from .clock import Clock, MonotonicClock
from .commands import ActionCommand, Command
from .connections import Connection, ConnectionRegistry
from .timers import (
    DISCONNECT_GRACE,
    TURN_DURATION,
    AutomaticAction,
    MatchResult,
    Timing,
)
from .views import player_view

REJECTED_REPLAY_CAPACITY = 256
logger = getLogger(__name__)
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
    def __init__(
        self,
        rooms: RoomManager,
        *,
        replay_capacity: int = REJECTED_REPLAY_CAPACITY,
        clock: Clock | None = None,
        turn_duration: int = TURN_DURATION,
        grace_duration: int = DISCONNECT_GRACE,
    ):
        self._rooms = rooms
        self._connections = ConnectionRegistry()
        if replay_capacity < 1 or min(turn_duration, grace_duration) < 1:
            raise ValueError("replay capacity and durations must be positive")
        self._capacity = replay_capacity
        self._clock = clock or MonotonicClock()
        self._turn_duration = turn_duration
        self._grace_duration = grace_duration
        self._timing = Timing()
        self._changed = asyncio.Event()
        self._retired = asyncio.Event()
        self._accepted: dict[
            tuple[Player, int], dict[str, tuple[Command, Acknowledgment]]
        ] = {}
        self._rejected: dict[
            tuple[Player, int], dict[str, tuple[Command, Acknowledgment]]
        ] = {}

    def admit(
        self, join: Callable[[str], AdmissionResult], room_code: str
    ) -> AdmissionResult:
        with self._rooms.synchronized():
            now = self._clock.now_ns()
            self._reconcile(now)
            admission = join(room_code)
            room = self._rooms.snapshot()
            assert room is not None and room.hand is not None
            self._publish_game(room, now)
            self._connections.publish_lobby(table_ready=True)
            self._sync_presence(now)
            return admission

    def attach(self, token: str, connection: Connection) -> Player | None:
        with self._rooms.synchronized():
            view = self._rooms.authenticate(token)
            if view is None:
                return None
            now = self._clock.now_ns()
            self._reconcile(now)
            connection.generation = self._rooms.generation
            self._connections.attach(view.seat, connection)
            room = self._rooms.snapshot()
            assert room is not None
            if not self._sync_presence(now) and connection.gameplay:
                connection.offer(self._view(room, view.seat, now))
            self._connections.publish_lobby(room.status == "ready")
            self._sync_presence(now)
            return view.seat

    def detach(self, seat: Player, connection: Connection) -> None:
        with self._rooms.synchronized():
            if (
                connection.generation != self._rooms.generation
                or not self._connections.owns(seat, connection)
            ):
                return
            now = self._clock.now_ns()
            self._reconcile(now)
            if self._connections.detach_if_current(seat, connection):
                room = self._rooms.snapshot()
                assert room is not None
                self._connections.publish_lobby(room.status == "ready")
            self._sync_presence(now)

    def reply(
        self, seat: Player, connection: Connection, payload: dict[str, object]
    ) -> None:
        with self._rooms.synchronized():
            if not self._is_current(seat, connection):
                return
            now = self._clock.now_ns()
            self._reconcile(now)
            if self._connections.is_current(seat, connection):
                connection.offer(payload)
            self._sync_presence(now)

    def snapshot(self, seat: Player, connection: Connection) -> None:
        with self._rooms.synchronized():
            if not self._is_current(seat, connection):
                return
            now = self._clock.now_ns()
            self._reconcile(now)
            if self._connections.is_current(seat, connection):
                room = self._rooms.snapshot()
                assert room is not None
                connection.offer(self._view(room, seat, now))
            self._sync_presence(now)

    def _is_current(self, seat: Player, connection: Connection) -> bool:
        return (
            connection.generation == self._rooms.generation
            and self._connections.is_current(seat, connection)
        )

    def legacy_status(
        self, token: str
    ) -> tuple[dict[str, object], asyncio.Event] | None:
        with self._rooms.synchronized():
            view = self._rooms.authenticate(token)
            if view is None:
                return None
            return (
                {
                    "type": "room_status",
                    "seat": view.seat,
                    "bet_unit": view.bet_unit,
                    "status": view.status,
                },
                self._retired,
            )

    def is_retired_token(self, token: str) -> bool:
        return self._rooms.is_retired_token(token)

    def terminal_command(
        self, seat: Player, connection: Connection, *, release: bool
    ) -> None:
        with self._rooms.synchronized():
            if not connection.gameplay or not self._is_current(seat, connection):
                return
            now = self._clock.now_ns()
            self._reconcile(now)
            if not self._is_current(seat, connection):
                self._sync_presence(now)
                return
            room = self._rooms.snapshot()
            assert room is not None
            if self._timing.result is None:
                connection.offer({"type": "error", "code": "ROOM_NOT_TERMINAL"})
                self._sync_presence(now)
            elif not release:
                changed = self._timing.acknowledge(seat)
                if changed is self._timing:
                    connection.offer(self._view(room, seat, now))
                else:
                    self._set_timing(changed)
                    self._publish_game(room, now)
            elif not self._timing.can_release(now):
                connection.offer({"type": "error", "code": "RELEASE_NOT_ELIGIBLE"})
                connection.offer(self._view(room, seat, now))
            else:
                self._rooms.retire(room)
                self._connections.retire()
                self._retired.set()
                self._retired = asyncio.Event()
                self._accepted.clear()
                self._rejected.clear()
                self._set_timing(Timing())

    def _view(self, room: Room, seat: Player, now: int) -> dict[str, object]:
        return player_view(room, seat, room.revision, self._timing, now)

    def _publish_game(self, room: Room, now: int) -> None:
        for seat, connection in self._connections.active():
            if connection.gameplay:
                connection.offer(self._view(room, seat, now))

    def _set_timing(self, timing: Timing) -> None:
        if timing != self._timing:
            self._timing = timing
            self._changed.set()

    def _sync_presence(self, now: int) -> bool:
        room = self._rooms.snapshot()
        if room is None:
            return False
        published = False
        # Each repeat can only lose another of the two writers to overflow.
        while True:
            active = {
                seat
                for seat, connection in self._connections.active()
                if connection.gameplay
            }
            timing = self._timing.with_presence(
                ("A" in active, "B" in active),
                room.hand,
                now,
                self._turn_duration,
                self._grace_duration,
            )
            if timing is self._timing:
                return published
            self._set_timing(timing)
            self._publish_game(room, now)
            published = True

    def _reconcile(self, now: int) -> None:
        room = self._rooms.snapshot()
        if room is None or room.hand is None:
            return
        result = self._timing.disconnect_result(now)
        if result is not None:
            self._set_timing(self._timing.finish(result, now))
            self._publish_game(room, now)
            return
        deadline = self._timing.turn_deadline
        if deadline is None or deadline > now:
            return
        hand = room.hand
        actor = hand.actor
        actions = legal_actions(hand, actor) if actor is not None else frozenset()
        if actor is None or actions.isdisjoint({"check", "fold"}):
            self._timing_failure(room, now)
            return
        move = "check" if "check" in actions else "fold"
        transition = apply_action(hand, actor, move)
        if not transition.accepted or transition.state == hand:
            self._timing_failure(room, now)
            return
        committed = self._rooms.commit_hand(room, transition.state)
        timing = self._timing.with_hand(transition.state, now, self._turn_duration)
        self._set_timing(
            replace(
                timing,
                last_automatic_action=AutomaticAction(hand.hand_number, actor, move),
            )
        )
        self._publish_game(committed, now)

    def _timing_failure(self, room: Room, now: int) -> None:
        logger.error(
            "Engine rejected its automatic action at revision %d", room.revision
        )
        self._set_timing(self._timing.finish(MatchResult("engine_error", None), now))
        self._publish_game(room, now)

    def tick(self, generation: int | None = None) -> None:
        with self._rooms.synchronized():
            if generation is not None and generation != self._rooms.generation:
                return
            now = self._clock.now_ns()
            self._reconcile(now)
            self._sync_presence(now)

    async def run_scheduler(self) -> None:
        generation = None
        while True:
            with self._rooms.synchronized():
                self.tick(generation)
                generation = self._rooms.generation
                deadline = self._timing.next_deadline
                self._changed.clear()
            # A wakeup never owns an old turn; it rereads the current deadline.
            await self._clock.wait(self._changed, deadline)

    def submit(self, seat: Player, connection: Connection, command: Command) -> None:
        with self._rooms.synchronized():
            if not self._is_current(seat, connection) or not connection.gameplay:
                return
            now = self._clock.now_ns()
            self._reconcile(now)
            self._sync_presence(now)
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
            previous = self._accepted.get(key, {}).get(command.action_id)
            if previous is None:
                previous = self._rejected.get(key, {}).get(command.action_id)

            if previous is not None and previous[0] == command:
                connection.offer(previous[1].message())
                self._sync_presence(now)
                return

            eligible = (
                previous is None
                and hand is not None
                and command.hand_id == hand.hand_number
            )
            if previous is not None:
                error = "REPLAY_CONFLICT"
            elif hand is None:
                error = "NOT_READY"
            elif command.hand_id != hand.hand_number:
                error = "WRONG_HAND"
            elif self._timing.result is not None:
                error = "MATCH_COMPLETE"
            elif not self._timing.activated:
                error = "NOT_READY"
            elif not all(self._timing.presence):
                error = "MATCH_PAUSED"
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
                history = self._accepted if outcome.accepted else self._rejected
                cache = history.setdefault(key, {})
                cache[command.action_id] = command, outcome
                if not outcome.accepted and len(cache) > self._capacity:
                    del cache[next(iter(cache))]
                if (
                    updated.hand is not None
                    and updated.hand.hand_number != command.hand_id
                ):
                    self._prune(updated.hand.hand_number)

            connection.offer(outcome.message())
            if updated is not room:
                self._set_timing(
                    self._timing.with_hand(updated.hand, now, self._turn_duration)
                )
                self._publish_game(updated, now)
            elif error in {"WRONG_HAND", "STALE_REVISION"}:
                connection.offer(self._view(room, seat, now))
            self._sync_presence(now)

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
        for history in (self._accepted, self._rejected):
            for key in tuple(history):
                if key[1] < hand_number - 1:
                    del history[key]
