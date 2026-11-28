"""Compare controlled deadline policies with the actual coordinator."""

from poker.engine import apply_action
from poker.rooms import RoomManager
from server.clock import SECOND
from server.commands import ActionCommand
from server.connections import Connection
from server.coordinator import GameCoordinator
from server.fixtures import ManualClock, fixed_deck


def setup():
    tokens = iter(("fixture-a", "fixture-b"))
    rooms = RoomManager(
        ruleset="legacy", token_factory=tokens.__next__, deck=fixed_deck("showdown")
    )
    clock = ManualClock()
    game = GameCoordinator(rooms, clock=clock)
    game.admit(rooms.join, rooms.create(10).room_code)
    for seat in ("a", "b"):
        connection = Connection(None, True)
        assert game.attach(f"fixture-{seat}", connection) == seat.upper()
        if seat == "a":
            a = connection
    return game, rooms, clock, a


def compare_pause():
    game, _, clock, a = setup()
    clock.advance_to(12 * SECOND)
    game.detach("A", a)
    clock.advance_to(20 * SECOND)
    a = Connection(None, True)
    game.attach("fixture-a", a)
    view = a.queue.get_nowait()
    saved = view["turn_clock"]["remaining_ms"] // 1000
    reset_deadline, preserved_deadline = 50, 20 + saved
    assert preserved_deadline == 38
    print(f"reset-on-reconnect: deadline={reset_deadline}, active_seconds=42")
    print(
        f"production pause/resume: deadline={preserved_deadline}, active_seconds={12 + saved}"
    )


def compare_delayed_scheduler():
    game, rooms, clock, a = setup()
    old = rooms.snapshot()
    clock.advance_to(35 * SECOND)
    modeled = apply_action(old.hand, "A", "call")
    assert modeled.accepted
    print(
        f"callback-only model at t=35 before the callback: late_call=True pot={modeled.state.pot}"
    )
    while not a.queue.empty():
        a.queue.get_nowait()
    game.submit(
        "A",
        a,
        ActionCommand(
            type="action",
            action_id="late",
            hand_id=1,
            expected_revision=1,
            action="call",
        ),
    )
    automatic, ack = a.queue.get_nowait(), a.queue.get_nowait()
    assert (automatic["last_automatic_action"]["action"], ack["accepted"]) == (
        "fold",
        False,
    )
    print(
        f"production ingress at t=35 before the scheduler: late_call={ack['accepted']} "
        f"automatic=fold pot={automatic['pot']} revision={automatic['revision']}"
    )


if __name__ == "__main__":
    compare_pause()
    compare_delayed_scheduler()
