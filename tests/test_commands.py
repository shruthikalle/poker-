import unittest

from pydantic import ValidationError

from poker.engine import apply_action
from poker.rooms import RoomManager
from server.commands import COMMAND_SCHEMA, ActionCommand, ReadyCommand
from server.fixtures import fixed_deck


class CommandSchemaTests(unittest.TestCase):
    def test_action_and_ready_shapes(self):
        common = {"action_id": "client-1", "hand_id": 1, "expected_revision": 3}
        self.assertIsInstance(
            COMMAND_SCHEMA.validate_python(
                {"type": "action", "action": "call", **common}
            ),
            ActionCommand,
        )
        self.assertIsInstance(
            COMMAND_SCHEMA.validate_python({"type": "ready", **common}), ReadyCommand
        )

    def test_exact_fields_types_and_bounds(self):
        good = {
            "type": "action",
            "action_id": "x",
            "hand_id": 1,
            "expected_revision": 0,
            "action": "call",
        }
        invalid = [
            {**good, **change}
            for change in (
                {"type": "unknown"},
                {"action": "ready"},
                {"action": "all-in"},
                {"action_id": ""},
                {"action_id": "x" * 65},
                {"action_id": "a n"},
                {"hand_id": True},
                {"hand_id": "1"},
                {"hand_id": 0},
                {"expected_revision": False},
                {"expected_revision": -1},
                {"expected_revision": 2**53},
                {"seat": "B"},
                {"amount": 100},
            )
        ]
        invalid.extend(
            {key: value for key, value in good.items() if key != name} for name in good
        )
        for payload in (*invalid, [], 42, None):
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    COMMAND_SCHEMA.validate_python(payload)

    def test_room_owns_revision_and_unchanged_commit_is_a_noop(self):
        rooms = RoomManager(ruleset="legacy", deck=fixed_deck("showdown"))
        host = rooms.create(10)
        self.assertEqual(rooms.snapshot().revision, 0)
        rooms.join(host.room_code)
        dealt = rooms.snapshot()
        self.assertEqual(dealt.revision, 1)
        self.assertEqual(dealt.hand.hole_cards[0], ("9h", "5h"))
        with rooms.synchronized():
            self.assertIs(rooms.commit_hand(dealt, dealt.hand), dealt)
            called = rooms.commit_hand(
                dealt, apply_action(dealt.hand, "A", "call").state
            )
        self.assertEqual((called.revision, called.hand.pot), (2, 20))
        self.assertIs(rooms.snapshot(), called)
