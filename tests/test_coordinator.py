import asyncio
import unittest
from unittest.mock import patch

from poker.engine import apply_action
from poker.rooms import RoomManager
from server.commands import ActionCommand, ReadyCommand
from server.connections import QUEUE_CAPACITY, Connection
from server.coordinator import GameCoordinator
from server.fixtures import fixed_deck


def action(action_id, revision, move="call", hand=1):
    return ActionCommand(
        type="action",
        action_id=action_id,
        expected_revision=revision,
        action=move,
        hand_id=hand,
    )


def ready(action_id, revision, hand=1):
    return ReadyCommand(
        type="ready", action_id=action_id, expected_revision=revision, hand_id=hand
    )


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        tokens = iter(("test-token-a", "test-token-b"))
        self.rooms = RoomManager(
            token_factory=tokens.__next__, deck=fixed_deck("showdown")
        )
        self.game = GameCoordinator(self.rooms, replay_capacity=4)
        room_code = self.rooms.create(10).room_code
        self.game.admit(self.rooms.join, room_code)
        self.a = self.attach("A")
        self.b = self.attach("B")
        self.assertEqual(self.a.queue.get_nowait()["lifecycle"], "active")

    def attach(self, seat):
        connection = Connection(None, gameplay=True)
        self.assertEqual(
            self.game.attach(f"test-token-{seat.lower()}", connection), seat
        )
        connection.queue.get_nowait()
        return connection

    def command(self, seat, message, *, changed=False, recover=False):
        caller, other = (self.a, self.b) if seat == "A" else (self.b, self.a)
        self.game.submit(seat, caller, message)
        ack = caller.queue.get_nowait()
        if changed:
            mine = caller.queue.get_nowait()
            theirs = other.queue.get_nowait()
            self.assertEqual(
                (mine["revision"], mine["stacks"], mine["pot"]),
                (theirs["revision"], theirs["stacks"], theirs["pot"]),
            )
        elif recover:
            self.assertEqual(
                caller.queue.get_nowait()["revision"], self.rooms.snapshot().revision
            )
        self.assertTrue(caller.queue.empty())
        self.assertTrue(other.queue.empty())
        return ack

    def test_replay_after_later_transition_skips_engine_and_conflicts_are_safe(self):
        call = action("shared", 1)
        with patch("server.coordinator.apply_action", wraps=apply_action) as engine:
            first = self.command("A", call, changed=True)
            self.command("B", action("shared", 2, "check"), changed=True)
            current = self.rooms.snapshot()
            self.assertEqual(self.command("A", call), first)
            for conflict in (action("shared", 1, "fold"), action("shared", 3)):
                self.assertEqual(
                    self.command("A", conflict)["error_code"], "REPLAY_CONFLICT"
                )
            self.assertEqual(engine.call_count, 2)
        self.assertEqual(
            (current.revision, current.hand.pot, current.hand.stacks),
            (3, 20, (190, 190)),
        )
        self.assertIs(self.rooms.snapshot(), current)

    def test_rejected_history_is_bounded_without_blocking_accepted_commands(self):
        current = self.rooms.snapshot()
        too_early = action("early", 1)
        rejected = self.command("B", too_early)
        self.assertEqual(rejected["error_code"], "WRONG_TURN")
        for i in range(256):
            failure = self.command("B", action(f"stale{i}", 0), recover=True)
            self.assertEqual(failure["error_code"], "STALE_REVISION")
        self.assertEqual(
            list(self.game._rejected[("B", 1)]), [f"stale{i}" for i in range(252, 256)]
        )
        self.assertEqual(
            self.command("B", action("stale255", 1))["error_code"], "REPLAY_CONFLICT"
        )
        self.assertIs(self.rooms.snapshot(), current)
        call = self.command("A", action("c", 1), changed=True)
        self.assertEqual(
            self.command("B", too_early, recover=True)["error_code"], "STALE_REVISION"
        )
        self.assertTrue(
            self.command("B", action("check", 2, "check"), changed=True)["accepted"]
        )
        self.assertEqual(self.command("A", action("c", 1)), call)

    def test_illegal_flood_cannot_consume_ready_capacity(self):
        self.command("A", action("fold", 1, "fold"), changed=True)
        for i in range(256):
            self.assertEqual(
                self.command("A", action(f"illegal{i}", 2))["error_code"],
                "HAND_COMPLETE",
            )
        first = self.command("A", ready("ready-a", 2), changed=True)
        self.assertTrue(first["accepted"])
        self.assertTrue(
            self.command("B", ready("ready-b", 3), changed=True)["accepted"]
        )
        self.assertEqual(self.command("A", ready("ready-a", 2)), first)

    def test_owner_replacement_and_unauthorized_commands(self):
        initial = self.rooms.snapshot()
        intruder = Connection(None, gameplay=True)
        self.assertIsNone(self.game.attach("wrong", intruder))
        old = self.a
        self.a = self.attach("A")
        self.assertEqual(old.close_code, 4000)
        self.game.submit("A", old, action("old", 1))
        self.game.submit("A", self.b, action("forged", 1))
        self.game.submit("A", intruder, action("intruder", 1))
        self.game.detach("A", old)
        self.assertIs(self.rooms.snapshot(), initial)
        self.assertTrue(self.command("A", action("new", 1), changed=True)["accepted"])

    def test_ready_across_hands_and_previous_replay_expiry(self):
        initial = self.rooms.snapshot()
        self.assertEqual(
            self.command("A", ready("early", 1))["error_code"], "ILLEGAL_ACTION"
        )
        self.assertIs(self.rooms.snapshot(), initial)
        folded = action("fold", 1, "fold")
        self.command("A", folded, changed=True)
        fold_state = self.rooms.snapshot()
        first_ready = ready("ready-a", 2)
        accepted = self.command("A", first_ready, changed=True)
        after_ready = self.rooms.snapshot()
        self.assertEqual(after_ready.hand.stacks, fold_state.hand.stacks)
        self.assertEqual(after_ready.hand.ready_players, (True, False))
        self.assertEqual(self.command("A", first_ready), accepted)
        self.assertEqual(
            self.command("A", ready("another", 3))["error_code"], "ILLEGAL_ACTION"
        )
        self.command("B", ready("ready-b", 3), changed=True)
        second = self.rooms.snapshot()
        self.assertEqual(
            (
                second.revision,
                second.hand.hand_number,
                second.hand.button,
                second.hand.stacks,
            ),
            (4, 2, "B", (185, 200)),
        )
        self.assertEqual(self.command("A", first_ready), accepted)
        self.assertEqual(
            self.command("A", action("old", 4), recover=True)["error_code"],
            "WRONG_HAND",
        )
        self.command("B", action("fold", 4, "fold", hand=2), changed=True)
        self.command("A", ready("ready-a", 5, 2), changed=True)
        self.command("B", ready("ready-b", 6, 2), changed=True)
        self.assertEqual(self.rooms.snapshot().revision, 7)
        self.assertEqual(
            self.command("A", first_ready, recover=True)["error_code"], "WRONG_HAND"
        )

    def test_ready_cannot_start_another_hand_after_match_completion(self):
        from dataclasses import replace

        before = self.rooms.snapshot()
        # Synthetic short-stack state, still totaling 400 with the posted pot.
        self.rooms.commit_hand(before, replace(before.hand, stacks=(10, 375)))
        self.command("A", action("fold", 2, "fold"), changed=True)
        ended = self.rooms.snapshot()
        self.assertEqual(ended.hand.match_winner, "B")
        self.assertEqual(
            self.command("B", ready("ready", 3))["error_code"], "MATCH_COMPLETE"
        )
        self.assertIs(self.rooms.snapshot(), ended)


class FakeSocket:
    def __init__(self, *, blocked=False, broken=False):
        self.entered = asyncio.Event()
        self.blocked = asyncio.Event() if blocked else None
        self.broken = broken
        self.sent = asyncio.Queue()

    async def send_json(self, payload):
        self.entered.set()
        if self.blocked is not None:
            await self.blocked.wait()
        if self.broken:
            raise OSError("offline")
        self.sent.put_nowait(payload)


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tokens = iter(("test-token-a", "test-token-b"))
        self.rooms = RoomManager(
            token_factory=tokens.__next__, deck=fixed_deck("showdown")
        )
        self.game = GameCoordinator(self.rooms)
        self.game.admit(self.rooms.join, self.rooms.create(10).room_code)

    def attach(self, seat, socket):
        connection = Connection(socket, gameplay=True)
        self.assertEqual(
            self.game.attach(f"test-token-{seat.lower()}", connection), seat
        )
        return connection

    async def receive(self, socket):
        return await asyncio.wait_for(socket.sent.get(), 2)

    async def test_stalled_writer_does_not_delay_actions_or_replacement(self):
        slow, normal = FakeSocket(blocked=True), FakeSocket()
        a, b = self.attach("A", slow), self.attach("B", normal)
        idle = asyncio.Event()
        a_writer = asyncio.create_task(a.run(idle.wait))
        b_writer = asyncio.create_task(b.run(idle.wait))
        try:
            await asyncio.wait_for(slow.entered.wait(), 2)
            self.assertEqual((await self.receive(normal))["revision"], 1)

            self.game.submit("A", a, action("call", 1))
            self.assertEqual((await self.receive(normal))["revision"], 2)
            self.game.submit("B", b, action("check", 2, "check"))
            self.assertTrue((await self.receive(normal))["accepted"])
            self.assertEqual((await self.receive(normal))["revision"], 3)

            new_socket = FakeSocket()
            replacement = self.attach("A", new_socket)
            await asyncio.wait_for(a_writer, 2)
            self.assertEqual(a.close_code, 4000)
            self.assertTrue(slow.sent.empty())
            self.game.detach("A", a)
            self.game.submit("A", a, action("replaced", 3, "fold"))
            self.assertEqual(replacement.queue.get_nowait()["revision"], 3)
            self.assertEqual(self.rooms.snapshot().revision, 3)
        finally:
            idle.set()
            await asyncio.gather(a_writer, b_writer)

    async def test_failed_send_preserves_commit_and_overflow_stops_authority(self):
        bad = FakeSocket(broken=True)
        a = self.attach("A", bad)
        b = self.attach("B", FakeSocket())
        self.game.submit("A", a, action("call", 1))
        await asyncio.wait_for(a.run(asyncio.Event().wait), 2)
        self.game.detach("A", a)
        authoritative = self.rooms.snapshot()
        self.assertEqual((authoritative.revision, authoritative.hand.pot), (2, 20))
        for _ in range(QUEUE_CAPACITY + 1):
            self.game.reply("B", b, {"type": "pong"})
        self.assertEqual(b.close_code, 1013)
        self.assertEqual(b.queue.qsize(), QUEUE_CAPACITY)
        self.game.submit("B", b, action("overflow", 2, "check"))
        self.assertIs(self.rooms.snapshot(), authoritative)

    async def test_competing_commands_against_one_revision(self):
        for same in (True, False):
            with self.subTest(duplicate=same):
                await self.asyncSetUp()
                a = self.attach("A", FakeSocket())
                self.attach("B", FakeSocket())
                while not a.queue.empty():
                    a.queue.get_nowait()
                barrier = asyncio.Barrier(3)

                async def submit(message):
                    await barrier.wait()
                    self.game.submit("A", a, message)

                with patch(
                    "server.coordinator.apply_action", wraps=apply_action
                ) as engine:
                    async with asyncio.TaskGroup() as group:
                        group.create_task(submit(action("call", 1)))
                        group.create_task(
                            submit(action("call" if same else "different", 1))
                        )
                        await barrier.wait()
                    self.assertEqual(engine.call_count, 1)
                replies = [a.queue.get_nowait() for _ in range(a.queue.qsize())]
                acks = [p for p in replies if p["type"] == "action_ack"]
                self.assertEqual(len(acks), 2)
                self.assertTrue(acks[0]["accepted"])
                if same:
                    self.assertEqual(acks[1], acks[0])
                else:
                    self.assertEqual(acks[1]["error_code"], "STALE_REVISION")
                self.assertEqual(
                    (self.rooms.snapshot().revision, self.rooms.snapshot().hand.pot),
                    (2, 20),
                )

    async def test_delayed_writer_resumes_in_revision_order(self):
        slow = FakeSocket(blocked=True)
        a = self.attach("A", slow)
        b = self.attach("B", FakeSocket())
        idle = asyncio.Event()
        writer = asyncio.create_task(a.run(idle.wait))
        try:
            await asyncio.wait_for(slow.entered.wait(), 2)
            self.game.submit("A", a, action("call", 1))
            self.game.submit("B", b, action("check", 2, "check"))
            slow.blocked.set()
            messages = [await self.receive(slow) for _ in range(5)]
            self.assertEqual(
                [
                    (m["type"], m.get("revision", m.get("outcome_revision")))
                    for m in messages
                ],
                [
                    ("snapshot", 1),
                    ("snapshot", 1),
                    ("action_ack", 2),
                    ("snapshot", 2),
                    ("snapshot", 3),
                ],
            )
        finally:
            idle.set()
            await asyncio.wait_for(writer, 2)

    async def test_one_legal_seat_wins_against_a_competing_wrong_turn(self):
        a, b = self.attach("A", FakeSocket()), self.attach("B", FakeSocket())
        for connection in (a, b):
            while not connection.queue.empty():
                connection.queue.get_nowait()
        barrier = asyncio.Barrier(3)

        async def submit(seat, connection):
            await barrier.wait()
            self.game.submit(seat, connection, action("same-revision", 1))

        async with asyncio.TaskGroup() as group:
            group.create_task(submit("A", a))
            group.create_task(submit("B", b))
            await barrier.wait()
        self.assertTrue(a.queue.get_nowait()["accepted"])
        b_messages = [b.queue.get_nowait() for _ in range(b.queue.qsize())]
        rejected = next(m for m in b_messages if m["type"] == "action_ack")
        self.assertIn(rejected["error_code"], {"WRONG_TURN", "STALE_REVISION"})
        self.assertEqual(
            (self.rooms.snapshot().revision, self.rooms.snapshot().hand.pot), (2, 20)
        )
