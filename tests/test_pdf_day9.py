"""PDF-rule command replay and same-revision races at the coordinator boundary."""

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from poker.rooms import RoomManager
from server.commands import ActionCommand
from server.connections import Connection
from server.coordinator import GameCoordinator
from server.fixtures import fixed_pdf_deck


def command(action_id: str, revision: int, move: str = "call") -> ActionCommand:
    return ActionCommand(
        type="action",
        action_id=action_id,
        expected_revision=revision,
        action=move,
        hand_id=1,
    )


def drain(connection: Connection) -> list[dict[str, object]]:
    return [connection.queue.get_nowait() for _ in range(connection.queue.qsize())]


def game() -> tuple[RoomManager, GameCoordinator, Connection, Connection]:
    tokens = iter(("day9-seat-a", "day9-seat-b"))
    rooms = RoomManager(
        ruleset="pdf", token_factory=tokens.__next__, deck=fixed_pdf_deck()
    )
    coordinator = GameCoordinator(rooms)
    code = rooms.create(10).room_code
    coordinator.admit(rooms.join, code)
    a, b = Connection(None, gameplay=True), Connection(None, gameplay=True)
    assert coordinator.attach("day9-seat-a", a) == "A"
    assert coordinator.attach("day9-seat-b", b) == "B"
    drain(a)
    drain(b)
    return rooms, coordinator, a, b


class PDFDay9CoordinatorTests(unittest.TestCase):
    def test_replay_precedes_stale_check_and_conflicts_preserve_state(self):
        rooms, coordinator, a, b = game()
        original = command("first-call", 1)
        coordinator.submit("A", a, original)
        first = drain(a)[0]
        drain(b)
        self.assertEqual((first["accepted"], first["outcome_revision"]), (True, 2))
        coordinator.submit("B", b, command("flop", 2, "check"))
        drain(a)
        drain(b)
        current = rooms.snapshot()
        self.assertEqual(
            (
                current.revision,
                current.hand.phase,
                current.hand.stacks,
                current.hand.pot,
            ),
            (3, "flop", (490, 490), 20),
        )

        coordinator.submit("A", a, original)
        self.assertEqual(drain(a), [first])
        self.assertIs(rooms.snapshot(), current)

        coordinator.submit("A", a, command("first-call", 1, "fold"))
        self.assertEqual(drain(a)[0]["error_code"], "REPLAY_CONFLICT")
        self.assertIs(rooms.snapshot(), current)

        coordinator.submit("A", a, command("new-stale-id", 1))
        messages = drain(a)
        self.assertEqual(messages[0]["error_code"], "STALE_REVISION")
        self.assertEqual(
            (messages[1]["type"], messages[1]["revision"]), ("snapshot", 3)
        )
        self.assertIs(rooms.snapshot(), current)

    def test_competing_same_revision_commands_commit_once(self):
        for duplicate in (False, True):
            with self.subTest(exact_duplicate=duplicate):
                rooms, coordinator, a, b = game()
                gate = Barrier(3)
                first = command("race", 1)
                second = first if duplicate else command("other-race", 1)

                def submit(move: ActionCommand) -> None:
                    gate.wait(timeout=3)
                    coordinator.submit("A", a, move)

                with ThreadPoolExecutor(max_workers=2) as pool:
                    jobs = [pool.submit(submit, move) for move in (first, second)]
                    gate.wait(timeout=3)
                    for job in jobs:
                        job.result(timeout=3)

                replies = drain(a)
                acknowledgments = [
                    reply for reply in replies if reply["type"] == "action_ack"
                ]
                self.assertEqual(len(acknowledgments), 2)
                self.assertEqual(
                    sum(reply["accepted"] for reply in acknowledgments),
                    2 if duplicate else 1,
                )
                if duplicate:
                    self.assertEqual(acknowledgments[0], acknowledgments[1])
                else:
                    self.assertEqual(
                        {reply["error_code"] for reply in acknowledgments},
                        {None, "STALE_REVISION"},
                    )
                state = rooms.snapshot()
                self.assertEqual(
                    (state.revision, state.hand.stacks, state.hand.pot),
                    (2, (490, 490), 20),
                )
                self.assertEqual(sum(state.hand.stacks) + state.hand.pot, 1000)
                self.assertEqual(
                    [
                        item["revision"]
                        for item in drain(b)
                        if item["type"] == "snapshot"
                    ],
                    [2],
                )


if __name__ == "__main__":
    unittest.main()
