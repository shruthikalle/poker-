"""Exercise room retirement with the real coordinator and a monotonic clock."""

import asyncio
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from poker.rooms import RoomManager
from server.clock import SECOND
from server.connections import ROOM_RETIRED_CLOSE, Connection
from server.coordinator import GameCoordinator
from server.fixtures import ManualClock
from test_coordinator import FakeSocket, action, ready


class Table:
    def __init__(self, *, ruleset="pdf"):
        self.rooms = RoomManager(code_factory=lambda: "TESTROOM", ruleset=ruleset)
        self.clock = ManualClock()
        self.game = GameCoordinator(self.rooms, clock=self.clock)

    def connect(self, admission, socket=None):
        connection = Connection(socket, gameplay=True)
        assert self.game.attach(admission.session_token, connection) == admission.seat
        return connection

    def play(self, unit=10):
        self.host = self.rooms.create(unit)
        self.guest = self.game.admit(self.rooms.join, self.host.room_code)
        self.a, self.b = self.connect(self.host), self.connect(self.guest)
        return self.rooms.snapshot()

    def complete(self):
        self.game.detach("B", self.b)
        self.clock.advance_to(self.clock.now_ns() + 20 * SECOND)
        self.game.tick()
        self.b = self.connect(self.guest)
        return self.rooms.snapshot()

    def terminal(self, *, release=False, seat="A"):
        self.game.terminal_command(
            seat, self.a if seat == "A" else self.b, release=release
        )

    def frames(self, seat="A"):
        queue = (self.a if seat == "A" else self.b).queue
        return [queue.get_nowait() for _ in range(queue.qsize())]


class PolicyTests(unittest.TestCase):
    def test_waiting_active_paused_and_settled_hand_cannot_release(self):
        table = Table()
        table.host = table.rooms.create(10)
        table.a = table.connect(table.host)
        table.terminal(release=True)
        self.assertEqual(table.frames()[-1]["code"], "ROOM_NOT_TERMINAL")
        table.guest = table.game.admit(table.rooms.join, table.host.room_code)
        table.b = table.connect(table.guest)
        active = table.rooms.snapshot()
        table.terminal(release=True)
        self.assertEqual(table.frames()[-1]["code"], "ROOM_NOT_TERMINAL")
        table.game.detach("B", table.b)
        table.terminal()
        self.assertEqual(table.frames()[-1]["code"], "ROOM_NOT_TERMINAL")
        self.assertIs(table.rooms.snapshot(), active)
        table.b = table.connect(table.guest)
        table.game.submit("A", table.a, action("fold", 1, "fold"))
        self.assertEqual(table.frames()[-1]["lifecycle"], "between_hands")
        table.terminal(release=True)
        self.assertEqual(table.frames()[-1]["code"], "ROOM_NOT_TERMINAL")

    def test_one_ack_uses_exact_terminal_retention_boundary(self):
        for offset in (-1, 0, 1):
            with self.subTest(offset=offset):
                table = Table()
                table.play()
                result = table.complete()
                table.clock.advance_to(30 * SECOND)
                table.terminal()
                acknowledged = table.frames()[-1]
                self.assertEqual(
                    acknowledged["room_release"],
                    {
                        "acknowledged": {"A": True, "B": False},
                        "eligible": False,
                        "remaining_ms": 50_000,
                    },
                )
                table.terminal()
                self.assertEqual(table.frames()[-1], acknowledged)
                table.clock.advance_to(80 * SECOND + offset)
                table.game.tick()
                self.assertIs(table.rooms.snapshot(), result)
                # The other seat may explicitly release after only A acknowledges.
                table.terminal(release=True, seat="B")
                if offset == -1:
                    error, view = table.frames("B")[-2:]
                    self.assertEqual(error["code"], "RELEASE_NOT_ELIGIBLE")
                    self.assertEqual(view["room_release"]["remaining_ms"], 1)
                    self.assertIs(table.rooms.snapshot(), result)
                else:
                    self.assertIsNone(table.rooms.snapshot())

    def test_both_absent_no_ack_retains_room_until_seat_returns(self):
        table = Table()
        table.play()
        table.game.detach("A", table.a)
        table.game.detach("B", table.b)
        table.clock.advance_to(100 * SECOND)
        table.game.tick()
        table.clock.advance_to(200 * SECOND)
        table.game.tick()
        self.assertIsNotNone(table.rooms.snapshot())
        table.a = table.connect(table.host)
        view = table.frames()[-1]
        self.assertEqual(
            view["match_result"], {"reason": "both_absent", "winner": None}
        )
        self.assertEqual(view["room_release"]["remaining_ms"], 0)
        table.terminal(release=True)
        self.assertEqual(table.frames()[-2]["code"], "RELEASE_NOT_ELIGIBLE")
        table.terminal()
        self.assertTrue(table.frames()[-1]["room_release"]["eligible"])
        self.assertIsNotNone(table.rooms.snapshot())
        table.terminal(release=True)
        self.assertIsNone(table.rooms.snapshot())

    def test_competing_acknowledgments_and_releases_retire_exactly_once(self):
        table = Table()
        initial = table.play()
        table.complete()

        def compete(release):
            barrier = Barrier(2)

            def send(seat):
                barrier.wait(timeout=2)
                table.terminal(seat=seat, release=release)

            with ThreadPoolExecutor(max_workers=2) as threads:
                list(threads.map(send, ("A", "B")))

        compete(False)
        self.assertEqual(
            table.frames()[-1]["room_release"]["acknowledged"], {"A": True, "B": True}
        )
        self.assertIs(table.rooms.snapshot(), initial)
        compete(True)
        self.assertIsNone(table.rooms.snapshot())
        self.assertEqual(table.rooms.generation, 1)
        self.assertEqual((table.a.close_code, table.b.close_code), (4001, 4001))

    def test_retired_connections_and_scheduler_cannot_touch_new_room(self):
        table = Table(ruleset="legacy")
        initial = table.play()
        old_a, old_b = table.a, table.b
        old_host, old_guest = table.host, table.guest
        table.game.submit("A", old_a, action("reused", 1))
        table.complete()
        table.terminal()
        table.terminal(seat="B")
        table.terminal(release=True)
        table.game.tick(initial.generation)
        self.assertIsNone(table.rooms.snapshot())
        fresh = table.play(12)
        self.assertNotEqual(old_host.room_code, table.host.room_code)
        self.assertIsNone(table.rooms.authenticate(old_host.session_token))
        self.assertIsNone(table.rooms.authenticate(old_guest.session_token))
        self.assertTrue(table.rooms.is_retired_token(old_guest.session_token))
        self.assertEqual((fresh.hand.button, fresh.hand.actor), ("A", "A"))
        self.assertEqual((fresh.revision, fresh.hand.hand_number), (1, 1))
        self.assertEqual((fresh.hand.stacks, fresh.hand.pot), ((234, 228), 18))
        self.assertEqual(fresh.hand.board, ())
        self.assertEqual(table.game._timing.turn_deadline, 50 * SECOND)

        table.frames()
        table.clock.advance_to(50 * SECOND)
        table.game.tick(initial.generation)
        table.game.detach("A", old_a)
        table.game.reply("A", old_a, {"type": "pong"})
        table.game.snapshot("A", old_a)
        table.game.submit("A", old_a, action("reused", 1))
        table.game.submit("B", old_b, ready("old-ready", 1))
        table.game.terminal_command("A", old_a, release=True)
        self.assertIsNone(
            table.game.attach(old_guest.session_token, Connection(None, True))
        )
        self.assertIs(table.rooms.snapshot(), fresh)
        self.assertEqual(table.game._timing.presence, (True, True))
        self.assertEqual(table.frames(), [])
        self.assertFalse(table.game._accepted or table.game._rejected)
        table.game.tick(fresh.generation)
        self.assertEqual(table.rooms.snapshot().revision, 2)


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_replaced_writer_and_delayed_cleanup_are_isolated(self):
        table = Table()
        table.play()
        table.complete()
        slow = FakeSocket(blocked=True)
        replaced, guest = table.a, table.b
        table.a = table.connect(table.host, slow)
        blocked = asyncio.create_task(table.a.run(asyncio.Event().wait))
        await asyncio.wait_for(slow.entered.wait(), 2)
        table.game.terminal_command("A", replaced, release=False)
        table.terminal(seat="B")
        self.assertFalse(table.frames("B")[-1]["room_release"]["eligible"])
        table.terminal()
        retiring = table.a
        table.terminal(release=True)
        fresh = table.play()
        await asyncio.wait_for(blocked, 2)
        table.game.detach("A", retiring)
        table.game.detach("B", guest)
        self.assertTrue(slow.sent.empty())
        self.assertEqual(retiring.close_code, ROOM_RETIRED_CLOSE)
        self.assertIs(table.rooms.snapshot(), fresh)
        self.assertEqual(table.game._timing.presence, (True, True))
