"""Pure, immutable betting state for a two-player Texas Hold'em hand.

The WebSocket layer should serialize requests, authenticate player identity,
deduplicate action IDs, and create player-specific views of this server state.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from random import SystemRandom
from typing import Literal

Player = Literal["A", "B"]
Phase = Literal["preflop", "flop", "turn", "river", "showdown", "finished"]
Action = Literal["fold", "check", "call", "bet", "raise"]

_RANKS = "23456789TJQKA"
_SUITS = "cdhs"
_FULL_DECK = tuple(f"{rank}{suit}" for rank in _RANKS for suit in _SUITS)
_NEXT_PHASE: dict[Phase, Phase] = {
    "preflop": "flop",
    "flop": "turn",
    "turn": "river",
    "river": "showdown",
}


def _index(player: Player) -> int:
    return 0 if player == "A" else 1


def _other(player: Player) -> Player:
    return "B" if player == "A" else "A"


def _set_pair(pair: tuple[int, int], player: Player, value: int) -> tuple[int, int]:
    result = list(pair)
    result[_index(player)] = value
    return result[0], result[1]


@dataclass(frozen=True)
class GameState:
    """Authoritative state; never send this object directly to a browser."""

    bet_unit: int
    button: Player
    stacks: tuple[int, int]
    contributions: tuple[int, int]
    pot: int
    hole_cards: tuple[tuple[str, str], tuple[str, str]]
    board: tuple[str, ...]
    deck: tuple[str, ...]
    phase: Phase
    actor: Player | None
    raise_count: int = 0
    checks_in_row: int = 0
    big_blind_option: bool = True
    winner: Player | None = None


@dataclass(frozen=True)
class ActionResult:
    """A valid move returns a new state; a rejection returns the original state."""

    accepted: bool
    state: GameState
    error: str | None = None


def new_game(bet_unit: int = 10, deck: tuple[str, ...] | None = None) -> GameState:
    """Create the first hand with A as button and 20 bet units per player."""

    if isinstance(bet_unit, bool) or not isinstance(bet_unit, int):
        raise ValueError("bet unit must be an even integer from 2 to 20")
    if bet_unit < 2 or bet_unit > 20 or bet_unit % 2:
        raise ValueError("bet unit must be an even integer from 2 to 20")
    if deck is None:
        cards = list(_FULL_DECK)
        SystemRandom().shuffle(cards)
        deck = tuple(cards)
    else:
        deck = tuple(deck)
    if len(deck) != 52 or set(deck) != set(_FULL_DECK):
        raise ValueError("deck must contain each of the 52 standard cards once")

    # Deal alternating cards, starting with the button.
    hole_cards = ((deck[0], deck[2]), (deck[1], deck[3]))
    chips = 20 * bet_unit
    return GameState(
        bet_unit=bet_unit,
        button="A",
        stacks=(chips - bet_unit // 2, chips - bet_unit),
        contributions=(bet_unit // 2, bet_unit),
        pot=bet_unit + bet_unit // 2,
        hole_cards=hole_cards,
        board=(),
        deck=deck[4:],
        phase="preflop",
        actor="A",
    )


def legal_actions(state: GameState, player: Player) -> frozenset[Action]:
    """Return only actions the current player can afford and perform."""

    if player not in ("A", "B") or state.actor != player:
        return frozenset()
    if state.phase in ("showdown", "finished"):
        return frozenset()

    own = _index(player)
    owed = max(state.contributions) - state.contributions[own]
    stack = state.stacks[own]
    actions: set[Action] = {"fold"}
    if owed:
        if stack > owed:
            actions.add("call")
        if state.raise_count < 2 and stack > owed + state.bet_unit:
            actions.add("raise")
    else:
        actions.add("check")
        if stack > state.bet_unit:
            if state.big_blind_option and state.phase == "preflop":
                if state.raise_count < 2:
                    actions.add("raise")
            elif max(state.contributions) == 0:
                actions.add("bet")
    return frozenset(actions)


def _pay(state: GameState, player: Player, amount: int) -> GameState:
    own = _index(player)
    return replace(
        state,
        stacks=_set_pair(state.stacks, player, state.stacks[own] - amount),
        contributions=_set_pair(
            state.contributions, player, state.contributions[own] + amount
        ),
        pot=state.pot + amount,
    )


def _advance_round(state: GameState) -> GameState:
    phase = _NEXT_PHASE[state.phase]
    if phase == "showdown":
        # Hand evaluation and pot award are the next engine milestone.
        return replace(
            state,
            phase=phase,
            actor=None,
            contributions=(0, 0),
            raise_count=0,
            checks_in_row=0,
            big_blind_option=False,
        )
    count = 3 if phase == "flop" else 1
    return replace(
        state,
        phase=phase,
        actor=_other(state.button),
        board=state.board + state.deck[:count],
        deck=state.deck[count:],
        contributions=(0, 0),
        raise_count=0,
        checks_in_row=0,
        big_blind_option=False,
    )


def apply_action(state: GameState, player: Player, action: str) -> ActionResult:
    """Apply one move, leaving the original state untouched on success or failure.

    The transport layer should call this only after authenticating the player.
    It should use ``accepted`` and ``error`` to form its reply, and retain
    ``state`` as the next authoritative state only when accepted is true.
    """

    if action not in legal_actions(state, player):
        return ActionResult(False, state, "illegal action or wrong turn")

    if action == "fold":
        winner = _other(player)
        chips = state.stacks[_index(winner)] + state.pot
        return ActionResult(
            True,
            replace(
                state,
                stacks=_set_pair(state.stacks, winner, chips),
                pot=0,
                phase="finished",
                actor=None,
                winner=winner,
            ),
        )

    own = _index(player)
    owed = max(state.contributions) - state.contributions[own]
    if action == "call":
        paid = _pay(state, player, owed)
        if state.big_blind_option:
            return ActionResult(True, replace(paid, actor=_other(player)))
        return ActionResult(True, _advance_round(paid))
    if action == "check":
        if state.big_blind_option or state.checks_in_row == 1:
            return ActionResult(True, _advance_round(state))
        return ActionResult(True, replace(state, actor=_other(player), checks_in_row=1))
    if action == "bet":
        paid = _pay(state, player, state.bet_unit)
        return ActionResult(
            True,
            replace(paid, actor=_other(player), checks_in_row=0),
        )
    # The remaining legal action is raise.
    paid = _pay(state, player, owed + state.bet_unit)
    return ActionResult(
        True,
        replace(
            paid,
            actor=_other(player),
            raise_count=state.raise_count + 1,
            checks_in_row=0,
            big_blind_option=False,
        ),
    )
