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
