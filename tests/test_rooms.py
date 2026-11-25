import unittest
from dataclasses import FrozenInstanceError

from poker.rooms import InvalidBetUnit, RoomAlreadyExists, RoomManager


class RoomCreationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rooms = RoomManager(
            code_factory=lambda: "test-room-code",
            token_factory=lambda: "test-session-a",
        )

    def test_accepts_every_even_bet_unit_inclusive(self) -> None:
        for bet_unit in (2, 4, 6, 8, 10, 12, 14, 16, 18, 20):
            with self.subTest(bet_unit=bet_unit):
                rooms = RoomManager()
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
        admission = RoomManager().create(10)
        self.assertRegex(admission.room_code, r"^[A-Za-z0-9_-]{12}$")
        self.assertRegex(admission.session_token, r"^[A-Za-z0-9_-]{43}$")

    def test_rejects_second_room_and_preserves_original_session(self) -> None:
        self.rooms.create(10)
        original = self.rooms.snapshot()

        with self.assertRaises(RoomAlreadyExists):
            self.rooms.create(12)

        self.assertIs(self.rooms.snapshot(), original)
