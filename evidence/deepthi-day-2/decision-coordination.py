"""Controlled split-check model versus the live coordinator, without sockets."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from json import dumps
from threading import Barrier, Lock
from unittest.mock import patch

from poker.engine import apply_action
from poker.rooms import RoomManager
from server.commands import ActionCommand
from server.connections import Connection
from server.coordinator import GameCoordinator
from server.fixtures import fixed_deck


def make_room():
    tokens = iter(("test-token-a", "test-token-b"))
    rooms = RoomManager(
        ruleset="legacy", token_factory=tokens.__next__, deck=fixed_deck("showdown")
    )
    rooms.join(rooms.create(10).room_code)
    return rooms


def summarize(hand, revision, accepted, calls):
    return {
        "accepted_transitions": accepted,
        "revision_increments": revision - 1,
        "engine_calls": calls,
        "a_chips_deducted": 195 - hand.stacks[0],
        "final_pot": hand.pot,
        "chips_conserved": sum(hand.stacks) + hand.pot == 400,
        "at_most_once": accepted == 1,
    }


def split_checks():
    starting = make_room().snapshot().hand
    hand, revision = starting, 1
    consumed = set()
    both_checked = Barrier(2, timeout=3)
    publish_lock = Lock()

    def retry():
        nonlocal hand, revision
        assert "call-1" not in consumed and revision == 1
        snapshot = hand
        both_checked.wait()
        result = apply_action(snapshot, "A", "call")
        assert result.accepted
        # The controlled alternative forgets to revalidate before publication.
        with publish_lock:
            hand = result.state
            revision += 1
            consumed.add("call-1")

    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(retry) for _ in range(2)]
        for job in jobs:
            job.result(timeout=3)
    return summarize(hand, revision, revision - 1, len(jobs))


async def atomic():
    rooms = make_room()
    coordinator = GameCoordinator(rooms)
    connection = Connection(None, gameplay=True)
    assert coordinator.attach("test-token-a", connection) == "A"
    assert coordinator.attach("test-token-b", Connection(None, gameplay=True)) == "B"
    while not connection.queue.empty():
        connection.queue.get_nowait()
    request = ActionCommand(
        type="action", action_id="call-1", hand_id=1, expected_revision=1, action="call"
    )
    barrier = asyncio.Barrier(3)

    async def retry():
        await barrier.wait()
        coordinator.submit("A", connection, request)

    with patch("server.coordinator.apply_action", wraps=apply_action) as engine:
        async with asyncio.TaskGroup() as group:
            group.create_task(retry())
            group.create_task(retry())
            await barrier.wait()
        calls = engine.call_count
    messages = [connection.queue.get_nowait() for _ in range(connection.queue.qsize())]
    acknowledgments = [
        message for message in messages if message["type"] == "action_ack"
    ]
    assert len(acknowledgments) == 2 and acknowledgments[0] == acknowledgments[1]
    current = rooms.snapshot()
    snapshots = sum(message["type"] == "snapshot" for message in messages)
    return summarize(current.hand, current.revision, snapshots, calls)


def main():
    split = split_checks()
    production = asyncio.run(atomic())
    print("controlled split checks:", dumps(split, sort_keys=True))
    print("production coordinator:", dumps(production, sort_keys=True))
    assert not split["at_most_once"] and production["at_most_once"]
    assert split["engine_calls"] == 2 and production["engine_calls"] == 1


if __name__ == "__main__":
    main()
