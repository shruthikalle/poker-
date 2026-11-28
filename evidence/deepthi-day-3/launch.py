"""Short real-time fixture settings for local recovery smoke checks."""

from poker.rooms import RoomManager
from poker.server import create_app
from server.clock import SECOND
from server.fixtures import fixed_deck


def timeout():
    return create_app(
        RoomManager(ruleset="legacy", deck=fixed_deck("showdown")),
        turn_duration=400_000_000,
    )


def recovery():
    return create_app(
        RoomManager(ruleset="legacy", deck=fixed_deck("showdown")),
        turn_duration=2 * SECOND,
        grace_duration=SECOND,
    )
