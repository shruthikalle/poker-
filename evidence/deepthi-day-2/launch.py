"""Loopback-only demonstration factories with fixed first hands."""

from poker.rooms import RoomManager
from poker.server import create_app
from server.fixtures import fixed_deck


def showdown():
    return create_app(RoomManager(ruleset="legacy", deck=fixed_deck("showdown")))


def tie():
    return create_app(RoomManager(ruleset="legacy", deck=fixed_deck("tie")))
