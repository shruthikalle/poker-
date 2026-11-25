"""Known-answer decks for local gameplay verification."""

from typing import Literal

Scenario = Literal["showdown", "fold", "tie"]

# Deal order is A, B, A, B, followed by the board with no burns.
WINNER_PREFIX = ("9h", "Ts", "5h", "3c", "Ah", "Kh", "Qh", "Jc", "2d")
TIE_PREFIX = ("2c", "3d", "4c", "5d", "As", "Ks", "Qs", "Js", "Ts")


def fixed_deck(scenario: Scenario) -> tuple[str, ...]:
    prefix = TIE_PREFIX if scenario == "tie" else WINNER_PREFIX
    return prefix + tuple(
        card
        for rank in "23456789TJQKA"
        for suit in "cdhs"
        if (card := rank + suit) not in prefix
    )


class ManualClock:
    """An event-loop-owned monotonic clock for deterministic verification."""

    def __init__(self):
        self._now = 0
        self._waiting = None

    def now_ns(self):
        return self._now

    def advance_to(self, nanoseconds):
        if nanoseconds < self._now:
            raise ValueError("a monotonic clock cannot go backward")
        self._now = nanoseconds
        if self._waiting is not None:
            self._waiting.set()

    async def wait(self, changed, deadline):
        if deadline is not None and deadline <= self._now:
            return
        self._waiting = changed
        try:
            await changed.wait()
        finally:
            self._waiting = None
