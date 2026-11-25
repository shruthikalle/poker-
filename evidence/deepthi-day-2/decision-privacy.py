"""Compare two representations of the same deterministic initial hand."""

from dataclasses import asdict
from json import dumps

from poker.rooms import RoomManager
from server.fixtures import fixed_deck
from server.views import player_view


def privacy_check(payload, opponent, unopened, internal, private):
    encoded = dumps(payload, sort_keys=True)
    report = {
        "opponent_cards": sorted(card for card in opponent if dumps(card) in encoded),
        "unrevealed_cards": sum(dumps(card) in encoded for card in unopened),
        "internal_fields": sorted(key for key in internal if dumps(key) in encoded),
        "private_room_fields": sum(dumps(value) in encoded for value in private),
    }
    report["passed"] = not any(report.values())
    return report


def main():
    tokens = iter(("test-token-a", "test-token-b"))
    rooms = RoomManager(
        code_factory=lambda: "test-code",
        token_factory=tokens.__next__,
        deck=fixed_deck("showdown"),
    )
    rooms.join(rooms.create(10).room_code)
    room = rooms.snapshot()
    hand = room.hand
    for label, candidate in (
        ("controlled raw GameState", asdict(hand)),
        ("production seat A snapshot", player_view(room, "A", 1)),
    ):
        result = privacy_check(
            candidate,
            hand.hole_cards[1],
            hand.deck,
            {"deck", "hole_cards", "checks_in_row", "big_blind_option"},
            {"test-code", "test-token-a", "test-token-b"},
        )
        print(f"{label}: {dumps(result, sort_keys=True)}")
        assert result["passed"] == (label == "production seat A snapshot")


if __name__ == "__main__":
    main()
