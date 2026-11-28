"""Run the same behavioral replay-capacity regression on both commits."""

from poker.rooms import RoomManager
from server.commands import ActionCommand
from server.connections import Connection
from server.coordinator import GameCoordinator


def main():
    tokens = iter(("fixture-a", "fixture-b"))
    rooms = RoomManager(ruleset="legacy", token_factory=tokens.__next__)
    game = GameCoordinator(rooms)
    game.admit(rooms.join, rooms.create(10).room_code)
    a = Connection(None, gameplay=True)
    b = Connection(None, gameplay=True)
    assert game.attach("fixture-a", a) == "A"
    assert game.attach("fixture-b", b) == "B"
    for connection in (a, b):
        while not connection.queue.empty():
            connection.queue.get_nowait()

    def send(action_id, revision):
        game.submit(
            "A",
            a,
            ActionCommand(
                type="action",
                action_id=action_id,
                hand_id=1,
                expected_revision=revision,
                action="call",
            ),
        )
        first = a.queue.get_nowait()
        while not a.queue.empty():
            a.queue.get_nowait()
        return first

    for i in range(256):
        assert send(f"stale-{i}", 0)["error_code"] == "STALE_REVISION"
    outcome = send("valid-call", 1)
    room = rooms.snapshot()
    print(
        f"after 256 stale commands: accepted={outcome['accepted']} "
        f"error={outcome['error_code']} revision={room.revision} pot={room.hand.pot}"
    )
    assert outcome["accepted"] and (room.revision, room.hand.pot) == (2, 20)


if __name__ == "__main__":
    main()
