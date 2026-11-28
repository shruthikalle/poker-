import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

from threading import Barrier

from poker.rooms import (
    InvalidBetUnit,
    RoomAlreadyExists,
    RoomFull,
    RoomManager,
    RoomNotFound,
)


class RoomCreationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rooms = RoomManager(
            ruleset="legacy",
            code_factory=lambda: "test-room-code",
            token_factory=lambda: "test-session-a",
        )

    def test_accepts_every_even_bet_unit_inclusive(self) -> None:
        for bet_unit in (2, 4, 6, 8, 10, 12, 14, 16, 18, 20):
            with self.subTest(bet_unit=bet_unit):
                rooms = RoomManager(ruleset="legacy")
                admission = rooms.create(bet_unit)
                self.assertEqual(admission.bet_unit, bet_unit)

    def test_rejects_invalid_bet_units_without_mutating_state(self) -> None:
        invalid_units = (0, 1, 3, 22, -2, 2.5, 10.0, "10", True, False, None)
        for bet_unit in invalid_units:
            with self.subTest(empty=True, bet_unit=bet_unit):
                with self.assertRaises(InvalidBetUnit):
                    self.rooms.create(bet_unit)
                self.assertIsNone(self.rooms.snapshot())

        self.rooms.create(10)
        waiting = self.rooms.snapshot()
        for bet_unit in invalid_units:
            with self.subTest(empty=False, bet_unit=bet_unit):
                with self.assertRaises(InvalidBetUnit):
                    self.rooms.create(bet_unit)
                self.assertIs(self.rooms.snapshot(), waiting)

    def test_creation_assigns_only_a_and_does_not_deal(self) -> None:
        admission = self.rooms.create(10)
        self.assertEqual(admission.room_code, "test-room-code")
        self.assertEqual(admission.seat, "A")
        self.assertEqual(admission.session_token, "test-session-a")
        self.assertEqual(admission.bet_unit, 10)
        self.assertEqual(admission.status, "waiting")

        room = self.rooms.snapshot()
        self.assertEqual(room.seat_a_token, "test-session-a")
        self.assertIsNone(room.seat_b_token)
        self.assertIsNone(room.hand)
        self.assertFalse(hasattr(room, "turn_deadline"))
        self.assertNotIn("test-session-a", repr(room))
        self.assertNotIn("test-session-a", repr(admission))
        with self.assertRaises(FrozenInstanceError):
            room.bet_unit = 12

    def test_default_generators_produce_url_safe_credentials(self) -> None:
        admission = RoomManager(ruleset="legacy").create(10)
        self.assertRegex(admission.room_code, r"^[A-Za-z0-9_-]{12}$")
        self.assertRegex(admission.session_token, r"^[A-Za-z0-9_-]{43}$")

    def test_rejects_second_room_and_preserves_original_session(self) -> None:
        self.rooms.create(10)
        original = self.rooms.snapshot()

        with self.assertRaises(RoomAlreadyExists):
            self.rooms.create(12)

        self.assertIs(self.rooms.snapshot(), original)


class RoomJoiningTests(unittest.TestCase):
    def setUp(self) -> None:
        tokens = iter(("test-session-a", "test-session-b"))
        self.rooms = RoomManager(
            ruleset="legacy",
            code_factory=lambda: "test-room-code",
            token_factory=tokens.__next__,
        )

    def test_join_assigns_b_and_initializes_one_hand_with_host_unit(self) -> None:
        host = self.rooms.create(12)
        guest = self.rooms.join(host.room_code)

        self.assertEqual((host.seat, guest.seat), ("A", "B"))
        self.assertEqual(guest.session_token, "test-session-b")
        self.assertNotEqual(host.session_token, guest.session_token)
        self.assertEqual(guest.room_code, host.room_code)
        self.assertEqual(guest.bet_unit, 12)
        self.assertEqual(guest.status, "ready")

        room = self.rooms.snapshot()
        self.assertEqual(room.seat_a_token, host.session_token)
        self.assertEqual(room.seat_b_token, guest.session_token)
        self.assertEqual(room.bet_unit, 12)
        hand = room.hand
        self.assertEqual(hand.bet_unit, 12)
        self.assertEqual(hand.stacks, (234, 228))
        self.assertEqual(hand.contributions, (6, 12))
        self.assertEqual(hand.pot, 18)
        self.assertEqual((hand.phase, hand.actor, hand.board), ("preflop", "A", ()))
        self.assertEqual(len(set(hand.hole_cards[0] + hand.hole_cards[1])), 4)

    def test_wrong_room_code_leaves_room_and_seats_unchanged(self) -> None:
        with self.assertRaises(RoomNotFound):
            self.rooms.join("test-room-code")
        self.assertIsNone(self.rooms.snapshot())

        self.rooms.create(10)
        waiting = self.rooms.snapshot()
        for invalid_code in ("wrong-room-code", "TEST-ROOM-CODE", None):
            with self.subTest(code=invalid_code):
                with self.assertRaises(RoomNotFound):
                    self.rooms.join(invalid_code)
                self.assertIs(self.rooms.snapshot(), waiting)

    def test_room_code_cannot_reclaim_a_seat_or_change_the_bet_unit(self) -> None:
        host = self.rooms.create(10)
        guest = self.rooms.join(host.room_code)
        full = self.rooms.snapshot()

        with self.assertRaises(RoomFull):
            self.rooms.join(host.room_code)
        with self.assertRaises(RoomAlreadyExists):
            self.rooms.create(20)

        self.assertIs(self.rooms.snapshot(), full)
        self.assertEqual(full.seat_a_token, host.session_token)
        self.assertEqual(full.seat_b_token, guest.session_token)
        self.assertEqual(full.bet_unit, 10)

    def test_join_retries_a_duplicate_token(self) -> None:
        tokens = iter(("test-session-a", "test-session-a", "test-session-b"))
        rooms = RoomManager(ruleset="legacy", token_factory=tokens.__next__)
        host = rooms.create(10)

        guest = rooms.join(host.room_code)

        self.assertEqual(guest.session_token, "test-session-b")
        self.assertEqual(rooms.snapshot().seat_a_token, "test-session-a")

    def test_repeated_token_collision_leaves_room_waiting(self) -> None:
        rooms = RoomManager(ruleset="legacy", token_factory=lambda: "test-session-a")
        host = rooms.create(10)
        waiting = rooms.snapshot()

        with self.assertRaisesRegex(RuntimeError, "unique session token"):
            rooms.join(host.room_code)

        self.assertIs(rooms.snapshot(), waiting)
        self.assertIsNone(waiting.hand)

    def test_competing_creations_allocate_only_one_host(self) -> None:
        start = Barrier(2, timeout=5)

        def create(bet_unit):
            start.wait()
            try:
                return self.rooms.create(bet_unit)
            except RoomAlreadyExists:
                return None

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(create, (10, 12)))

        self.assertEqual(results.count(None), 1)
        winner = next(admission for admission in results if admission is not None)
        room = self.rooms.snapshot()
        self.assertEqual(room.seat_a_token, "test-session-a")
        self.assertEqual(room.seat_a_token, winner.session_token)
        self.assertEqual(room.bet_unit, winner.bet_unit)
        self.assertIsNone(room.seat_b_token)

    def test_competing_joins_allocate_only_one_guest_and_preserve_host(self) -> None:
        host = self.rooms.create(10)
        start = Barrier(2, timeout=5)

        def join():
            start.wait()
            try:
                return self.rooms.join(host.room_code)
            except RoomFull:
                return None

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(join) for _ in range(2)]
            results = [future.result() for future in futures]

        self.assertEqual(results.count(None), 1)
        winner = next(admission for admission in results if admission is not None)
        room = self.rooms.snapshot()
        self.assertEqual(winner.seat, "B")
        self.assertEqual(room.seat_b_token, winner.session_token)
        self.assertEqual(room.seat_a_token, host.session_token)
        self.assertEqual(room.bet_unit, 10)
        self.assertEqual(room.hand.pot, 15)
