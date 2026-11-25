"""Known-answer timing boundaries through the real coordinator."""

import asyncio
import json
import unittest
from unittest.mock import patch

from poker.engine import apply_action
from poker.rooms import RoomManager
from server.clock import SECOND
from server.connections import QUEUE_CAPACITY, Connection
from server.coordinator import GameCoordinator
from server.fixtures import ManualClock, fixed_deck
from test_coordinator import FakeSocket, action, ready


class Game:
    def __init__(self):
        tokens = iter(("timed-a", "timed-b"))
        self.clock = ManualClock()
        self.rooms = RoomManager(
            token_factory=tokens.__next__, deck=fixed_deck("showdown")
        )
        self.coordinator = GameCoordinator(
            self.rooms, clock=self.clock, replay_capacity=4
        )
        self.host = self.rooms.create(10)
        self.sockets = {}

    def at(self, seconds, offset=0):
        self.clock.advance_to(seconds * SECOND + offset)

    def join(self):
        self.coordinator.admit(self.rooms.join, self.host.room_code)

    def connect(self, seat, *, gameplay=True, socket=None):
        conn = Connection(socket, gameplay=gameplay)
        assert self.coordinator.attach(f"timed-{seat.lower()}", conn) == seat
        self.sockets[seat] = conn
        return conn

    def disconnect(self, seat):
        self.coordinator.detach(seat, self.sockets[seat])

    def drain(self, seat):
        queue = self.sockets[seat].queue
        return [queue.get_nowait() for _ in range(queue.qsize())]

    def view(self, seat):
        self.coordinator.snapshot(seat, self.sockets[seat])
        messages = self.drain(seat)
        assert messages and messages[-1]["type"] == "snapshot"
        return messages[-1]

    def command(self, seat, request):
        self.coordinator.submit(seat, self.sockets[seat], request)
        return self.drain(seat)

    def playing(self):
        self.join()
        self.connect("A")
        self.connect("B")
        self.drain("A")
        self.drain("B")
        return self


class DeadlineTests(unittest.TestCase):
    def test_waiting_and_initial_activation_only_counts_gameplay(self):
        game = Game()
        game.connect("A")
        self.assertEqual(game.view("A")["lifecycle"], "waiting")
        game.join()
        game.connect("B", gameplay=False)
        game.at(100)
        waiting = game.view("A")
        self.assertEqual(waiting["lifecycle"], "awaiting_players")
        self.assertEqual(waiting["turn_clock"]["status"], "inactive")
        self.assertEqual(waiting["disconnect_grace"], {"A": None, "B": None})
        self.assertEqual(waiting["legal_actions"], [])
        game.connect("B")
        a, b = game.view("A"), game.view("B")
        self.assertEqual(
            a["turn_clock"],
            {"status": "running", "acting_player": "A", "remaining_ms": 30000},
        )
        self.assertEqual(a["revision"], 1)
        self.assertEqual(a["lifecycle_revision"], b["lifecycle_revision"])
        self.assertEqual(a["presence"], {"A": True, "B": True})
        self.assertEqual(a["own_hole_cards"], ["9h", "5h"])
        self.assertEqual(b["own_hole_cards"], ["Ts", "3c"])

    def test_command_before_deadline_wins_and_new_deadline_is_fresh(self):
        game = Game().playing()
        game.at(30, -1)
        ack, new = game.command("A", action("call", 1))
        self.assertTrue(ack["accepted"])
        self.assertEqual(
            (new["actor"], new["pot"], new["turn_clock"]["remaining_ms"]),
            ("B", 20, 30000),
        )
        game.at(30)
        game.coordinator.tick()
        self.assertEqual(game.rooms.snapshot().revision, 2)
        self.assertIsNone(game.view("B")["last_automatic_action"])

    def test_exact_and_late_commands_reconcile_automatic_fold_before_ack(self):
        for offset in (0, 1, 35 * SECOND):
            with self.subTest(offset=offset):
                game = Game().playing()
                game.at(30, offset)
                settlement, rejection, recovery = game.command("A", action("call", 1))
                self.assertEqual(rejection["error_code"], "STALE_REVISION")
                self.assertEqual(settlement, recovery)
                self.assertEqual(
                    settlement["last_automatic_action"],
                    {
                        "source": "server",
                        "reason": "turn_timeout",
                        "hand_id": 1,
                        "seat": "A",
                        "action": "fold",
                    },
                )
                self.assertEqual(settlement["stacks"], {"A": 195, "B": 205})
                self.assertEqual((settlement["pot"], settlement["revision"]), (0, 2))
                self.assertEqual(settlement["turn_clock"]["status"], "inactive")
                self.assertNotIn('"Ts"', json.dumps(settlement))
                game.coordinator.tick()
                self.assertEqual(game.rooms.snapshot().revision, 2)

    def test_automatic_check_with_same_actor_starts_a_new_turn(self):
        game = Game().playing()
        game.command("A", action("call", 1))
        game.drain("B")
        game.at(35)
        game.coordinator.tick()
        view = game.view("B")
        self.assertEqual(
            (view["phase"], view["actor"], view["revision"]), ("flop", "B", 3)
        )
        self.assertEqual(view["stacks"], {"A": 190, "B": 190})
        self.assertEqual(view["pot"], 20)
        self.assertEqual(view["last_automatic_action"]["action"], "check")
        self.assertEqual(view["turn_clock"]["remaining_ms"], 30000)
        self.assertEqual(view["board"], ["Ah", "Kh", "Qh"])
        self.assertNotIn('"Jc"', json.dumps(view))

    def test_read_rejection_and_replay_do_not_reset_clock_or_revise(self):
        game = Game().playing()
        call = action("call", 1)
        accepted = game.command("A", call)[0]
        game.drain("B")
        game.at(5)
        state = game.view("A")
        game.coordinator.reply("A", game.sockets["A"], {"type": "pong"})
        self.assertEqual(game.drain("A"), [{"type": "pong"}])
        self.assertEqual(game.command("A", call), [accepted])
        self.assertEqual(
            game.command("A", action("wrong", 2))[0]["error_code"], "WRONG_TURN"
        )
        self.assertEqual(game.view("A"), state)
        self.assertEqual(state["turn_clock"]["remaining_ms"], 25000)

    def test_pause_at_12_and_resume_at_20_expires_at_38(self):
        game = Game().playing()
        game.at(12)
        game.disconnect("A")
        paused = game.view("B")
        self.assertEqual(paused["turn_clock"]["remaining_ms"], 18000)
        self.assertEqual(
            paused["disconnect_grace"], {"A": {"remaining_ms": 20000}, "B": None}
        )
        self.assertEqual(paused["legal_actions"], [])
        self.assertEqual(
            game.command("B", action("paused", 1))[0]["error_code"], "MATCH_PAUSED"
        )
        game.at(19)
        frozen = game.view("B")
        self.assertEqual(frozen["turn_clock"], paused["turn_clock"])
        self.assertEqual(frozen["lifecycle_revision"], paused["lifecycle_revision"])
        game.at(20)
        game.connect("A")
        resumed = game.view("A")
        self.assertEqual(resumed["turn_clock"]["remaining_ms"], 18000)
        self.assertEqual(resumed["own_hole_cards"], ["9h", "5h"])
        game.at(30)
        game.coordinator.tick()
        self.assertEqual(game.rooms.snapshot().revision, 1)
        game.at(38)
        game.coordinator.tick()
        self.assertEqual(game.view("B")["result"], {"kind": "fold_win", "winner": "B"})

    def test_repeated_resume_and_stale_callbacks_preserve_13_seconds(self):
        game = Game().playing()
        for loss, back, seat, remaining in ((10, 15, "A", 20000), (22, 30, "B", 13000)):
            game.at(loss)
            game.disconnect(seat)
            game.at(back)
            game.connect(seat)
            self.assertEqual(game.view(seat)["turn_clock"]["remaining_ms"], remaining)
            game.drain("B" if seat == "A" else "A")
        game.at(43, -1)
        game.coordinator.tick()
        self.assertEqual(game.rooms.snapshot().revision, 1)
        game.at(43)
        game.coordinator.tick()
        self.assertEqual(game.rooms.snapshot().hand.stacks, (195, 205))

    def test_disconnect_before_at_and_after_turn_expiry(self):
        for offset in (-1, 0, 1):
            with self.subTest(offset=offset):
                game = Game().playing()
                game.at(30, offset)
                game.disconnect("B")
                a = game.view("A")
                self.assertEqual(a["lifecycle"], "paused")
                self.assertEqual(
                    a["turn_clock"]["status"], "paused" if offset < 0 else "inactive"
                )
                self.assertEqual(a["revision"], 1 if offset < 0 else 2)
                self.assertEqual(a["pot"], 15 if offset < 0 else 0)

    def test_overlapping_and_simultaneous_absence_close_with_no_winner(self):
        for first, second, later in (("A", "B", 17), ("B", "A", 17), ("A", "B", 10)):
            with self.subTest(first=first, later=later):
                game = Game().playing()
                game.at(10)
                game.disconnect(first)
                game.at(later)
                game.disconnect(second)
                game.at(30, -1)
                game.coordinator.tick()
                self.assertIsNone(game.coordinator._timing.result)
                game.at(30)
                game.coordinator.tick()
                game.at(38)
                game.connect("A")
                result = game.view("A")
                self.assertEqual(
                    result["match_result"], {"reason": "both_absent", "winner": None}
                )
                self.assertEqual(result["presence"], {"A": False, "B": False})
                self.assertIsNone(result["result"])
                self.assertNotIn('"Ts"', json.dumps(result))
                self.assertEqual(
                    (result["stacks"], result["pot"]), ({"A": 195, "B": 190}, 15)
                )
                self.assertEqual(
                    game.command("A", ready("too-late", 1))[0]["error_code"],
                    "MATCH_COMPLETE",
                )
                self.assertIsNone(game.coordinator._timing.next_deadline)

    def test_either_player_returns_before_earliest_disconnect_expiry(self):
        for returning, expiry in (("A", 37), ("B", 30)):
            with self.subTest(returning=returning):
                game = Game().playing()
                game.at(10)
                game.disconnect("A")
                game.at(17)
                game.disconnect("B")
                game.at(25)
                game.connect(returning)
                view = game.view(returning)
                self.assertEqual(view["turn_clock"]["remaining_ms"], 20000)
                absent = "A" if returning == "B" else "B"
                self.assertEqual(
                    view["disconnect_grace"][absent],
                    {"remaining_ms": (expiry - 25) * 1000},
                )
                game.at(expiry)
                game.coordinator.tick()
                final = game.view(returning)
                self.assertEqual(
                    final["match_result"], {"reason": "forfeit", "winner": returning}
                )
                self.assertEqual(final["pot"], 15)
                self.assertEqual(final["turn_clock"]["status"], "inactive")

    def test_reconnect_at_exact_deadline_or_later_cannot_preempt_forfeit(self):
        for offset in (-1, 0, 1):
            with self.subTest(offset=offset):
                game = Game().playing()
                game.at(10)
                game.disconnect("A")
                game.at(30, offset)
                game.connect("A")
                new = game.view("A")
                if offset < 0:
                    self.assertEqual(new["turn_clock"]["remaining_ms"], 20000)
                    self.assertEqual(new["lifecycle"], "active")
                else:
                    self.assertEqual(
                        new["match_result"], {"reason": "forfeit", "winner": "B"}
                    )
                    self.assertEqual(new["pot"], 15)
                    self.assertNotIn('"Ts"', json.dumps(new))
                    self.assertEqual(
                        game.command("A", action("late", 1))[0]["error_code"],
                        "MATCH_COMPLETE",
                    )

    def test_replacement_lobby_downgrade_and_invalid_auth(self):
        game = Game().playing()
        old = game.sockets["A"]
        game.at(5)
        game.connect("A")
        self.assertEqual(old.close_code, 4000)
        game.coordinator.detach("A", old)
        self.assertEqual(game.view("A")["turn_clock"]["remaining_ms"], 25000)
        self.assertEqual(game.coordinator._timing.grace, (None, None))
        game.connect("A", gameplay=False)
        self.assertEqual(game.view("B")["presence"], {"A": False, "B": True})
        game.at(10)
        game.connect("A", gameplay=False)
        self.assertIsNone(
            game.coordinator.attach("invalid-token", Connection(None, True))
        )
        self.assertEqual(
            game.view("B")["disconnect_grace"]["A"], {"remaining_ms": 15000}
        )
        game.connect("A")
        self.assertEqual(game.view("A")["turn_clock"]["remaining_ms"], 25000)

    def test_reconnect_replays_and_ready_restarts_full_clock(self):
        game = Game().playing()
        fold = action("fold", 1, "fold")
        first = game.command("A", fold)[0]
        game.drain("B")
        self.assertEqual(game.view("A")["lifecycle"], "between_hands")
        game.disconnect("A")
        paused = game.view("B")
        self.assertEqual(paused["turn_clock"]["status"], "inactive")
        self.assertFalse(paused["can_ready"])
        self.assertEqual(
            game.command("B", ready("paused-ready", 2))[0]["error_code"], "MATCH_PAUSED"
        )
        game.at(15)
        game.connect("A")
        game.view("A")
        game.drain("B")
        self.assertEqual(game.command("A", fold), [first])
        game.command("A", ready("ra", 2))
        game.drain("B")
        game.command("B", ready("rb", 3))
        new = game.view("A")
        self.assertEqual((new["hand_id"], new["revision"], new["actor"]), (2, 4, "B"))
        self.assertEqual(new["turn_clock"]["remaining_ms"], 30000)

    def test_expiry_runs_despite_replay_flood_and_exact_retry_is_safe(self):
        game = Game().playing()
        for i in range(256):
            game.command("A", action(f"stale{i}", 0))
        call = action("accepted", 1)
        original = game.command("A", call)[0]
        game.drain("B")
        game.at(30)
        with patch("server.coordinator.apply_action", wraps=apply_action) as engine:
            automatic, replay = game.command("A", call)
            self.assertEqual(engine.call_count, 1)
        self.assertEqual(replay, original)
        self.assertEqual(automatic["revision"], 3)
        self.assertEqual(automatic["last_automatic_action"]["action"], "check")

    def test_queue_overflow_creates_grace_and_replacement_clears_it(self):
        game = Game().playing()
        original = game.sockets["A"]
        game.at(10)
        for _ in range(QUEUE_CAPACITY + 1):
            game.coordinator.reply("A", original, {"type": "pong"})
        self.assertEqual(original.close_code, 1013)
        self.assertEqual(
            game.view("B")["disconnect_grace"]["A"], {"remaining_ms": 20000}
        )
        game.at(11)
        game.connect("A")
        game.coordinator.detach("A", original)
        self.assertEqual(game.view("A")["turn_clock"]["remaining_ms"], 20000)


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_scheduler_expiry_is_independent_of_a_blocked_writer(self):
        game = Game()
        game.join()
        slow = FakeSocket(blocked=True)
        a = game.connect("A", socket=slow)
        game.connect("B")
        game.drain("B")
        reader_wait = asyncio.Event()
        writer = asyncio.create_task(a.run(reader_wait.wait))
        scheduler = asyncio.create_task(game.coordinator.run_scheduler())
        try:
            await asyncio.wait_for(slow.entered.wait(), 2)
            game.at(30)
            outcome = await asyncio.wait_for(game.sockets["B"].queue.get(), 2)
            self.assertEqual(outcome["result"], {"kind": "fold_win", "winner": "B"})
            self.assertEqual(outcome["revision"], 2)
            self.assertTrue(slow.sent.empty())
        finally:
            reader_wait.set()
            scheduler.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await scheduler
            await asyncio.wait_for(writer, 2)

    async def test_scheduler_wakes_for_earlier_grace_without_old_turn_action(self):
        game = Game().playing()
        task = asyncio.create_task(game.coordinator.run_scheduler())
        try:
            game.at(1)
            game.disconnect("A")
            paused = await asyncio.wait_for(game.sockets["B"].queue.get(), 2)
            self.assertEqual(paused["turn_clock"]["status"], "paused")
            game.at(21)
            outcome = await asyncio.wait_for(game.sockets["B"].queue.get(), 2)
            self.assertEqual(
                outcome["match_result"], {"reason": "forfeit", "winner": "B"}
            )
            self.assertEqual(outcome["revision"], 1)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
