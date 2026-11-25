"""Room timing and match outcomes, independent of poker chip settlement."""

from dataclasses import dataclass, replace
from typing import Literal

from poker.engine import GameState, Player

from .clock import SECOND

SEATS: tuple[Player, Player] = ("A", "B")
TURN_DURATION = 30 * SECOND
DISCONNECT_GRACE = 20 * SECOND
Presence = tuple[bool, bool]
DeadlinePair = tuple[int | None, int | None]


@dataclass(frozen=True)
class MatchResult:
    reason: Literal["engine", "forfeit", "both_absent"]
    winner: Player | None


@dataclass(frozen=True)
class AutomaticAction:
    hand_id: int
    seat: Player
    action: Literal["check", "fold"]


@dataclass(frozen=True)
class Timing:
    presence: Presence = (False, False)
    activated: bool = False
    revision: int = 0
    turn_deadline: int | None = None
    saved_turn: int | None = None
    grace: DeadlinePair = (None, None)
    result: MatchResult | None = None
    last_automatic_action: AutomaticAction | None = None

    @property
    def next_deadline(self) -> int | None:
        return min(
            (
                deadline
                for deadline in (self.turn_deadline, *self.grace)
                if deadline is not None
            ),
            default=None,
        )

    def with_presence(
        self,
        presence: Presence,
        hand: GameState | None,
        now: int,
        turn_duration: int,
        grace_duration: int,
    ) -> "Timing":
        if self.result is not None or presence == self.presence:
            return self
        changed = replace(self, presence=presence, revision=self.revision + 1)
        if not self.activated:
            if hand is not None and all(presence):
                return replace(changed, activated=True).with_hand(
                    hand, now, turn_duration
                )
            return changed

        def deadline(index: int) -> int | None:
            if presence[index]:
                return None
            if self.presence[index]:
                return now + grace_duration
            return self.grace[index]

        changed = replace(changed, grace=(deadline(0), deadline(1)))
        if all(presence) and self.saved_turn is not None:
            return replace(
                changed, turn_deadline=now + self.saved_turn, saved_turn=None
            )
        if not all(presence) and self.turn_deadline is not None:
            return replace(
                changed, saved_turn=max(0, self.turn_deadline - now), turn_deadline=None
            )
        return changed

    def with_hand(self, hand: GameState, now: int, turn_duration: int) -> "Timing":
        last = self.last_automatic_action
        if last is not None and last.hand_id != hand.hand_number:
            last = None
        changed = replace(self, last_automatic_action=last)
        if hand.match_winner is not None:
            return changed.finish(MatchResult("engine", hand.match_winner))
        deadline = (
            now + turn_duration
            if self.activated and all(self.presence) and hand.actor
            else None
        )
        return replace(changed, turn_deadline=deadline, saved_turn=None)

    def finish(self, result: MatchResult) -> "Timing":
        return replace(
            self,
            result=result,
            turn_deadline=None,
            saved_turn=None,
            grace=(None, None),
            revision=self.revision + 1,
        )

    def disconnect_result(self, now: int) -> MatchResult | None:
        if not any(value is not None and value <= now for value in self.grace):
            return None
        if not any(self.presence):
            return MatchResult("both_absent", None)
        return MatchResult("forfeit", "A" if self.presence[0] else "B")
