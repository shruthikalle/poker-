"""Local known-answer rooms for browser verification."""

from dataclasses import replace

from poker.rooms import RoomManager
from poker.server import create_app
from server.clock import SECOND
from server.fixtures import fixed_deck


def fixture(scenario, *, turn=30 * SECOND, grace=3 * SECOND):
    return create_app(
        RoomManager(code_factory=lambda: "FRIEND42", deck=fixed_deck(scenario)),
        turn_duration=turn,
        grace_duration=grace,
    )


def showdown():
    return fixture("showdown")


def tie():
    return fixture("tie")


def timeout():
    return fixture("showdown", turn=900_000_000)


def expiry():
    return fixture("showdown", grace=650_000_000)


class ShortStackRoom(RoomManager):
    """Supply a reachable terminal accounting boundary without playing earlier hands."""

    def join(self, room_code):
        with self.synchronized():
            admission = super().join(room_code)
            dealt = self.snapshot()
            assert dealt is not None and dealt.hand is not None
            self.commit_hand(dealt, replace(dealt.hand, stacks=(10, 375)))
            return admission


def short_stack():
    return create_app(
        ShortStackRoom(code_factory=lambda: "FRIEND42", deck=fixed_deck("showdown"))
    )
