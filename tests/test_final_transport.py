"""Bounded transport stress and independently expected admission invariants."""

import asyncio
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import Barrier, Event

from fastapi.testclient import TestClient

from poker.rooms import RoomManager
from poker.server import create_app
from server.connections import QUEUE_CAPACITY, Connection
from server.fixtures import ManualClock, fixed_deck
from test_coordinator import FakeSocket, action, ready
from test_deadlines import Game


class AdmissionRaceTests(unittest.TestCase):
    def test_distinct_keys_and_legacy_join_share_capacity(self):
        tokens = iter(("audit-host", "audit-guest"))
        rooms = RoomManager(
            ruleset="legacy",
            code_factory=lambda: "AUDITROOM",
            token_factory=tokens.__next__,
            deck=fixed_deck("showdown"),
        )
        with TestClient(create_app(rooms)) as client:

            def race(path, body, keys):
                start = Barrier(len(keys))

                def send(key):
                    headers = {"Admission-Key": key} if key is not None else {}
                    start.wait(timeout=3)
                    return client.post(path, json=body, headers=headers)

                with ThreadPoolExecutor(max_workers=len(keys)) as pool:
                    return list(pool.map(send, keys))

            create_keys = ("a" * 64, "b" * 64)
            create_body = {"bet_unit": 10}
            results = race("/api/rooms", create_body, create_keys)
            self.assertEqual(sorted(r.status_code for r in results), [201, 409])
            chosen = next(
                i for i, result in enumerate(results) if result.status_code == 201
            )
            original = results[chosen].json()
            self.assertEqual(original["session_token"], "audit-host")
            join_keys = ("c" * 64, "d" * 64)
            join_body = {"room_code": original["room_code"]}
            results = race("/api/rooms/join", join_body, join_keys)
            self.assertEqual(sorted(r.status_code for r in results), [200, 409])
            guest = next(
                i for i, result in enumerate(results) if result.status_code == 200
            )
            self.assertEqual(results[guest].json()["session_token"], "audit-guest")
            joined = rooms.snapshot()
            self.assertEqual((joined.revision, joined.hand.hand_number), (1, 1))
            self.assertEqual((joined.hand.stacks, joined.hand.pot), ((195, 190), 15))

            path = "/api/rooms/join"
            replay = client.post(
                path, json=join_body, headers={"Admission-Key": join_keys[guest]}
            )
            self.assertEqual(replay.json(), results[guest].json())
            self.assertEqual(replay.headers["cache-control"], "no-store")
            self.assertEqual(client.post("/api/join", json=join_body).status_code, 409)
            self.assertEqual(
                client.post(
                    "/api/rooms",
                    json=create_body,
                    headers={"Admission-Key": create_keys[chosen]},
                ).json(),
                original,
            )
            self.assertIs(rooms.snapshot(), joined)
            self.assertEqual(len(rooms._admissions), 2)
            self.assertTrue(
                all(len(digest) == 32 for digest, _, _ in rooms._admissions)
            )

    def test_replay_and_conflicting_reuse_race_with_first_socket(self):
        rooms = RoomManager(
            ruleset="legacy",
            code_factory=lambda: "AUDITROOM",
            deck=fixed_deck("showdown"),
        )
        with TestClient(create_app(rooms)) as client:
            headers = {"Admission-Key": "a" * 64}
            original = client.post(
                "/api/rooms", json={"bet_unit": 10}, headers=headers
            ).json()
            join = client.post("/api/rooms/join", json={"room_code": "AUDITROOM"})
            self.assertEqual(join.status_code, 200)
            before = rooms.snapshot()
            start = Barrier(3)

            def replay(unit):
                start.wait(timeout=3)
                return client.post(
                    "/api/rooms", json={"bet_unit": unit}, headers=headers
                )

            def authenticate():
                start.wait(timeout=3)
                with client.websocket_connect("/ws") as ws:
                    ws.send_json(
                        {
                            "type": "auth",
                            "token": original["session_token"],
                            "protocol": "gameplay.v1",
                        }
                    )
                    return ws.receive_json()

            with ThreadPoolExecutor(max_workers=3) as pool:
                same = pool.submit(replay, 10)
                conflict = pool.submit(replay, 12)
                initial = pool.submit(authenticate)
                self.assertEqual(same.result(timeout=4).json(), original)
                self.assertEqual(
                    conflict.result(timeout=4).json(),
                    {"detail": "admission key conflict"},
                )
                snapshot = initial.result(timeout=4)
            self.assertEqual(
                (snapshot["seat"], snapshot["revision"], snapshot["pot"]), ("A", 1, 15)
            )
            self.assertEqual(snapshot["own_hole_cards"], ["9h", "5h"])
            self.assertIs(rooms.snapshot(), before)


class LifespanAuditTests(unittest.TestCase):
    def test_scheduler_cancels_on_app_shutdown_across_lifecycles(self):
        class ObservedClock(ManualClock):
            def __init__(self):
                super().__init__()
                self.waiting = Event()
                self.cancelled = Event()

            async def wait(self, changed, deadline):
                self.waiting.set()
                try:
                    await super().wait(changed, deadline)
                except asyncio.CancelledError:
                    self.cancelled.set()
                    raise

        for lifecycle in ("waiting", "active", "paused", "complete"):
            with self.subTest(lifecycle=lifecycle):
                clock = ObservedClock()
                rooms = RoomManager(ruleset="legacy", deck=fixed_deck("showdown"))
                durations = {"grace_duration": 1} if lifecycle == "complete" else {}
                with TestClient(create_app(rooms, clock=clock, **durations)) as client:
                    host = client.post("/api/rooms", json={"bet_unit": 10}).json()

                    def connect(stack, admission):
                        ws = stack.enter_context(client.websocket_connect("/ws"))
                        ws.send_json(
                            {
                                "type": "auth",
                                "token": admission["session_token"],
                                "protocol": "gameplay.v1",
                            }
                        )
                        return ws

                    with ExitStack() as host_stack:
                        a = connect(host_stack, host)
                        self.assertEqual(a.receive_json()["lifecycle"], "waiting")
                        if lifecycle != "waiting":
                            guest = client.post(
                                "/api/rooms/join", json={"room_code": host["room_code"]}
                            ).json()
                            self.assertEqual(
                                a.receive_json()["lifecycle"], "awaiting_players"
                            )
                            with ExitStack() as guest_stack:
                                b = connect(guest_stack, guest)
                                self.assertEqual(
                                    b.receive_json()["lifecycle"], "active"
                                )
                                self.assertEqual(
                                    a.receive_json()["lifecycle"], "active"
                                )
                            if lifecycle in ("paused", "complete"):
                                paused = a.receive_json()
                                self.assertEqual(paused["lifecycle"], "paused")
                                if lifecycle == "complete":
                                    client.portal.call(clock.advance_to, 1)
                                    final = a.receive_json()
                                    self.assertEqual(final["lifecycle"], "complete")
                                    self.assertEqual(
                                        final["match_result"],
                                        {"reason": "forfeit", "winner": "A"},
                                    )
                        self.assertTrue(clock.waiting.wait(timeout=2))
                self.assertTrue(clock.cancelled.is_set())


class ResourceAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_fifty_replacements_retire_writers_and_bound_replay(self):
        game = Game()
        game.join()
        writers = {}
        sockets = {}
        peak_writers = 0
        peak_queue = 0

        async def attach(seat):
            nonlocal peak_writers, peak_queue
            old = game.sockets.get(seat)
            socket = FakeSocket()
            new = game.connect(seat, socket=socket)
            writer = asyncio.create_task(new.run(asyncio.Event().wait))
            writers[new] = writer
            sockets[seat] = socket
            peak_writers = max(peak_writers, len(writers))
            peak_queue = max(peak_queue, new.queue.qsize())
            snapshot = await asyncio.wait_for(socket.sent.get(), 2)
            self.assertEqual(snapshot["seat"], seat)
            if old:
                self.assertEqual(old.close_code, 4000)
                await asyncio.wait_for(writers.pop(old), 2)
                game.coordinator.detach(seat, old)
                game.coordinator.submit(seat, old, action("old", snapshot["revision"]))
                self.assertEqual(game.rooms.snapshot().revision, snapshot["revision"])
            return new

        try:
            await attach("A")
            await attach("B")
            first_hand = game.rooms.snapshot().hand.hand_number
            for number in range(50):
                seat = "A" if number % 2 == 0 else "B"
                new = await attach(seat)
                game.coordinator.snapshot(seat, new)
                snapshot = await asyncio.wait_for(sockets[seat].sent.get(), 2)
                self.assertEqual((snapshot["revision"], snapshot["pot"]), (1, 15))
                self.assertEqual(len(game.coordinator._connections.active()), 2)
                self.assertEqual(len(writers), 2)

            # Fold and Ready through five legitimate hands to exercise replay pruning.
            async def accepted(seat, command):
                game.coordinator.submit(seat, game.sockets[seat], command)
                for _ in range(6):
                    frame = await asyncio.wait_for(sockets[seat].sent.get(), 2)
                    if frame["type"] == "action_ack":
                        self.assertTrue(frame["accepted"])
                        return
                self.fail("accepted command acknowledgment missing")

            highest_accepted = 0
            for hand in range(first_hand, first_hand + 5):
                current = game.rooms.snapshot()
                self.assertEqual(current.hand.hand_number, hand)
                self.assertEqual(sum(current.hand.stacks) + current.hand.pot, 400)
                actor = "A" if hand % 2 else "B"
                await accepted(actor, action("fold", current.revision, "fold", hand))
                settled = game.rooms.snapshot()
                self.assertEqual((settled.hand.pot, sum(settled.hand.stacks)), (0, 400))
                await accepted("A", ready("ready", settled.revision, hand))
                await accepted(
                    "B", ready("ready", game.rooms.snapshot().revision, hand)
                )
                records = game.coordinator._accepted
                self.assertTrue(
                    all(identifier in (hand, hand + 1) for _, identifier in records)
                )
                highest_accepted = max(
                    highest_accepted, sum(map(len, records.values()))
                )
        finally:
            for seat, connection in game.sockets.items():
                connection.request_close(1000)
                game.coordinator.detach(seat, connection)
            await asyncio.wait_for(asyncio.gather(*writers.values()), 2)
        self.assertEqual(game.coordinator._connections.active(), ())
        self.assertTrue(all(writer.done() for writer in writers.values()))
        self.assertLessEqual(peak_queue, QUEUE_CAPACITY)
        self.assertEqual(peak_writers, 3)
        emit_audit_metrics(peak_queue, peak_writers, highest_accepted)

    async def test_run_cancels_blocked_writer_and_reader(self):
        idle = asyncio.Event()
        entered = asyncio.Event()
        released = asyncio.Event()

        async def read():
            entered.set()
            try:
                await idle.wait()
            finally:
                released.set()

        blocked = FakeSocket(blocked=True)
        connection = Connection(blocked, gameplay=True)
        connection.offer({"type": "pending"})
        runner = asyncio.create_task(connection.run(read))
        await asyncio.wait_for(entered.wait(), 2)
        await asyncio.wait_for(blocked.entered.wait(), 2)
        runner.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(runner, 2)
        self.assertTrue(released.is_set())
        self.assertTrue(blocked.sent.empty())


def emit_audit_metrics(peak_queue, peak_writers, highest_accepted):
    print(
        f"Resource audit: 50 replacements; peak tracked writers {peak_writers}; active writers 0 after shutdown; "
        f"sampled attach queue peak {peak_queue}/{QUEUE_CAPACITY}; peak retained accepted commands {highest_accepted}",
        flush=True,
    )
