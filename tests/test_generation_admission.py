"""Exercise generation-bound admission through FastAPI and real socket handlers."""

import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from secrets import token_hex
from unittest.mock import patch

from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from poker.rooms import RoomManager
from poker.server import create_app
from server.clock import SECOND
from server.connections import QUEUE_CAPACITY, Connection
from server.coordinator import GameCoordinator
from server.fixtures import ManualClock

EXPIRED = {"detail": "ADMISSION_EXPIRED"}


def keyed(context):
    return {"Admission-Key": f"{context}.{token_hex(32)}"}


def authorize(socket, admission):
    socket.send_json(
        {"type": "auth", "protocol": "gameplay.v1", "token": admission["session_token"]}
    )


def receive(socket, predicate):
    for _ in range(12):
        frame = socket.receive_json()
        if predicate(frame):
            return frame
    raise AssertionError("expected socket frame did not arrive within 12 frames")


class GenerationAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.resources = ExitStack()
        self.addCleanup(self.resources.close)
        self.clock = ManualClock()
        self.rooms = RoomManager()
        self.game = GameCoordinator(self.rooms, clock=self.clock)
        self.writers = self.peak_writers = self.peak_attach_queue = 0
        self.schedulers = self.scheduler_starts = 0
        original_run = Connection.run
        original_scheduler = self.game.run_scheduler

        async def run(connection, reader):
            self.writers += 1
            self.peak_writers = max(self.peak_writers, self.writers)
            self.peak_attach_queue = max(
                self.peak_attach_queue, connection.queue.qsize()
            )
            try:
                await original_run(connection, reader)
            finally:
                self.writers -= 1

        async def scheduler():
            self.scheduler_starts += 1
            self.schedulers += 1
            try:
                await original_scheduler()
            finally:
                self.schedulers -= 1

        self.resources.enter_context(patch.object(Connection, "run", run))
        self.resources.enter_context(
            patch.object(self.game, "run_scheduler", scheduler)
        )
        with patch("poker.server.GameCoordinator", return_value=self.game):
            app = create_app(self.rooms, clock=self.clock)
        self.resources.callback(
            lambda: self.assertEqual((self.schedulers, self.writers), (0, 0))
        )
        self.client = self.resources.enter_context(TestClient(app))

    def context(self):
        response = self.client.get("/api/admission-context")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        return response.json()["context"]

    def create(self, headers=None, path="/api/rooms"):
        return self.client.post(path, json={"bet_unit": 10}, headers=headers)

    def join(self, code, headers=None, path="/api/rooms/join"):
        return self.client.post(path, json={"room_code": code}, headers=headers)

    def closed(self, socket, code=4001):
        with self.assertRaises(WebSocketDisconnect) as failure:
            receive(socket, lambda _: False)
        self.assertEqual(failure.exception.code, code)

    def retired_or_unauthorized(self, admission):
        response = self.client.get(
            "/api/session",
            headers={"Authorization": f"Bearer {admission['session_token']}"},
        )
        self.assertEqual(response.status_code, 401)
        with self.client.websocket_connect("/ws") as socket:
            authorize(socket, admission)
            with self.assertRaises(WebSocketDisconnect) as failure:
                socket.receive_json()
            self.assertEqual(failure.exception.code, 4001)

    def reach_terminal(self, stack, host, guest):
        a = stack.enter_context(self.client.websocket_connect("/ws"))
        authorize(a, host)
        with self.client.websocket_connect("/ws") as b:
            authorize(b, guest)
            active = receive(b, lambda frame: frame.get("lifecycle") == "active")
            self.assertEqual(
                (
                    active["hand_id"],
                    active["revision"],
                    active["button"],
                    active["actor"],
                ),
                (1, 1, "A", "A"),
            )
            self.assertEqual(
                (active["stacks"], active["pot"], active["board"]),
                ({"A": 495, "B": 490}, 15, []),
            )
            self.assertNotIn("deck", active)
            self.assertIsNone(active["match_result"])
            self.assertNotIn("room_release", active)
            self.assertIsNone(active["last_automatic_action"])
            self.assertEqual(active["disconnect_grace"], {"A": None, "B": None})
            self.assertEqual(active["turn_clock"]["remaining_ms"], 30_000)
        receive(a, lambda frame: frame.get("lifecycle") == "paused")
        self.client.portal.call(
            self.clock.advance_to, self.clock.now_ns() + 20 * SECOND
        )
        terminal = receive(a, lambda frame: frame.get("lifecycle") == "complete")
        self.assertEqual(terminal["match_result"], {"reason": "forfeit", "winner": "A"})
        self.assertEqual(terminal["pot"], 15)
        self.assertIsNone(terminal["result"])
        b = stack.enter_context(self.client.websocket_connect("/ws"))
        authorize(b, guest)
        a.send_json({"type": "acknowledge_result"})
        b.send_json({"type": "acknowledge_result"})
        receive(a, lambda frame: frame.get("room_release", {}).get("eligible"))
        return a, b

    def test_25_rollovers_prune_successes_without_reaccepting_first_keys(self):
        first = None
        codes, tokens = set(), set()
        for generation in range(25):
            with self.subTest(generation=generation), ExitStack() as stack:
                context = self.context()
                create_key, join_key = keyed(context), keyed(context)
                created = self.create(create_key)
                self.assertEqual(created.status_code, 201)
                host = created.json()
                self.assertTrue(
                    self.create(create_key).json() == host, "create replay changed"
                )
                joined = self.join(host["room_code"], join_key)
                self.assertEqual(joined.status_code, 200)
                guest = joined.json()
                self.assertTrue(
                    self.join(host["room_code"], join_key).json() == guest,
                    "join replay changed",
                )
                self.assertEqual(
                    self.join(host["room_code"], create_key).json(),
                    {"detail": "admission key conflict"},
                )
                self.assertEqual(len(self.rooms._admissions), 2)
                self.assertNotIn(host["room_code"], codes)
                codes.add(host["room_code"])
                pair = {host["session_token"], guest["session_token"]}
                self.assertTrue(
                    len(pair) == 2 and tokens.isdisjoint(pair), "tokens were reused"
                )
                tokens.update(pair)
                if first is None:
                    first = (create_key, join_key, host["room_code"])
                else:
                    self.assertEqual(self.create(first[0]).json(), EXPIRED)
                    self.assertEqual(self.join(first[2], first[1]).json(), EXPIRED)
                a, b = self.reach_terminal(stack, host, guest)
                # A status-only socket is separately fenced without replacing gameplay A.
                status = stack.enter_context(self.client.websocket_connect("/ws"))
                status.send_json(
                    {"type": "authenticate", "session_token": host["session_token"]}
                )
                self.assertEqual(status.receive_json()["type"], "room_status")
                a.send_json({"type": "release_room"})
                for socket in (a, b, status):
                    self.closed(socket)
                self.assertEqual(self.rooms.generation, generation + 1)
                self.assertIsNone(self.rooms.snapshot())
                self.assertEqual(self.rooms._admissions, [])
                self.assertEqual(self.game._connections.active(), ())
                self.assertEqual((self.game._accepted, self.game._rejected), ({}, {}))
                self.assertEqual(self.game._timing.next_deadline, None)
                self.assertEqual((self.writers, self.schedulers), (0, 1))
                self.assertEqual(self.create(create_key).json(), EXPIRED)
                self.assertEqual(self.join(host["room_code"], join_key).json(), EXPIRED)
                self.retired_or_unauthorized(host)
                self.retired_or_unauthorized(guest)
        self.assertEqual((len(codes), len(tokens)), (25, 50))
        self.assertEqual(self.scheduler_starts, 1)
        self.assertLessEqual(self.peak_attach_queue, QUEUE_CAPACITY)
        print(
            f"Rollover audit: 25 rooms; 50 distinct tokens; {self.scheduler_starts} scheduler start; "
            f"peak active gameplay/lobby writers {self.peak_writers}; "
            f"sampled initial queue peak {self.peak_attach_queue}/{QUEUE_CAPACITY}; "
            "0 writers, replay entries, admission records or deadlines after each release",
            flush=True,
        )

    def test_release_racing_with_admission_preserves_all_four_contracts(self):
        old_context = self.context()
        old_key = {"Admission-Key": token_hex(32)}
        host = self.create(old_key).json()
        guest = self.join(host["room_code"], path="/api/join").json()
        with ExitStack() as stack, ThreadPoolExecutor(max_workers=4) as threads:
            a, _ = self.reach_terminal(stack, host, guest)
            delayed_key = keyed(old_context)
            contenders = [threads.submit(self.create, delayed_key) for _ in range(3)]
            a.send_json({"type": "release_room"})
            self.closed(a)
            for attempt in contenders:
                response = attempt.result(timeout=3)
                self.assertEqual(response.status_code, 409)
                self.assertIn(
                    response.json(),
                    (EXPIRED, {"detail": "an active room already exists"}),
                )
            self.assertIsNone(self.rooms.snapshot())
            context = self.context()
            self.assertTrue(context != old_context, "context did not rotate")
            for create_path in ("/api/table", "/api/rooms"):
                self.assertEqual(self.create(path=create_path).json(), EXPIRED)
                self.assertEqual(self.create(old_key, create_path).json(), EXPIRED)
            for join_path in ("/api/join", "/api/rooms/join"):
                self.assertEqual(
                    self.join(host["room_code"], path=join_path).json(), EXPIRED
                )
            stale = threads.submit(self.create, delayed_key)
            fresh = threads.submit(
                self.create, {"Admission-Context": context}, "/api/table"
            )
            self.assertEqual(stale.result(timeout=3).json(), EXPIRED)
            admitted = fresh.result(timeout=3)
            self.assertEqual(admitted.status_code, 201)
            self.assertEqual(
                set(admitted.json()), {"room_code", "seat", "session_token"}
            )
            scoped = {"Admission-Context": context}
            self.assertEqual(self.join(host["room_code"], scoped).status_code, 404)
            self.assertEqual(
                self.join(
                    admitted.json()["room_code"], scoped, "/api/join"
                ).status_code,
                201,
            )
            self.retired_or_unauthorized(host)

    def test_scoped_keys_fail_closed_after_restart(self):
        context = self.context()
        previous = keyed(context)
        self.assertEqual(self.create(previous).status_code, 201)
        with TestClient(create_app()) as restarted:
            replay = restarted.post(
                "/api/rooms", json={"bet_unit": 10}, headers=previous
            )
            self.assertEqual(replay.status_code, 409)
            self.assertEqual(replay.json(), EXPIRED)
            self.assertEqual(
                restarted.post("/api/rooms", json={"bet_unit": 10}).status_code, 201
            )
