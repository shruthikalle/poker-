"""Known-answer decks for local gameplay verification."""

from typing import Literal

Scenario = Literal["showdown", "fold", "tie"]

# Deal order is A, B, A, B, followed by the board with no burns.
WINNER_PREFIX = ("9h", "Ts", "5h", "3c", "Ah", "Kh", "Qh", "Jc", "2d")
TIE_PREFIX = ("2c", "3d", "4c", "5d", "As", "Ks", "Qs", "Js", "Ts")
PDF_WINNER_PREFIX = (
    "9h",
    "Ts",
    "5h",
    "3c",
    "2c",
    "Ah",
    "Kh",
    "Qh",
    "4d",
    "Jc",
    "6s",
    "2d",
)


def fixed_deck(scenario: Scenario) -> tuple[str, ...]:
    prefix = TIE_PREFIX if scenario == "tie" else WINNER_PREFIX
    return prefix + tuple(
        card
        for rank in "23456789TJQKA"
        for suit in "cdhs"
        if (card := rank + suit) not in prefix
    )


def fixed_pdf_deck() -> tuple[str, ...]:
    """A flush-over-straight deal with one burn before each board street."""
    return PDF_WINNER_PREFIX + tuple(
        card
        for rank in "23456789TJQKA"
        for suit in "cdhs"
        if (card := rank + suit) not in PDF_WINNER_PREFIX
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
