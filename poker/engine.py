"""Pure, immutable betting state for a two-player Texas Hold'em hand.

The WebSocket layer should serialize requests, authenticate player identity,
deduplicate action IDs, and create player-specific views of this server state.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from random import SystemRandom
from typing import Literal

from treys import Card, Evaluator

Player = Literal["A", "B"]
Phase = Literal["preflop", "flop", "turn", "river", "showdown", "finished"]
Action = Literal["fold", "check", "call", "bet", "raise", "ready"]
Ruleset = Literal["legacy", "pdf"]

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
    match_winner: Player | None = None
    ready_players: tuple[bool, bool] = (False, False)
    hand_number: int = 1
    ruleset: Ruleset = "pdf"
    burn_cards: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActionResult:
    """A valid move returns a new state; a rejection returns the original state."""

    accepted: bool
    state: GameState
    error: str | None = None


def _deck_or_shuffle(deck: tuple[str, ...] | None) -> tuple[str, ...]:
    if deck is None:
        cards = list(_FULL_DECK)
        SystemRandom().shuffle(cards)
        deck = tuple(cards)
    else:
        deck = tuple(deck)
    if len(deck) != 52 or set(deck) != set(_FULL_DECK):
        raise ValueError("deck must contain each of the 52 standard cards once")
    return deck


def _deal_hole_cards(
    deck: tuple[str, ...], button: Player
) -> tuple[tuple[str, str], tuple[str, str]]:
    if button == "A":
        return ((deck[0], deck[2]), (deck[1], deck[3]))
    return ((deck[1], deck[3]), (deck[0], deck[2]))


def new_game(
    bet_unit: int = 10,
    deck: tuple[str, ...] | None = None,
    *,
    ruleset: Ruleset = "pdf",
) -> GameState:
    """Create the first hand; the PDF rules use fixed 500-chip stacks."""

    if isinstance(bet_unit, bool) or not isinstance(bet_unit, int):
        raise ValueError("bet unit must be an even integer from 2 to 20")
    if bet_unit < 2 or bet_unit > 20 or bet_unit % 2:
        raise ValueError("bet unit must be an even integer from 2 to 20")
    if ruleset not in ("legacy", "pdf"):
        raise ValueError("unknown ruleset")
    if ruleset == "pdf" and bet_unit != 10:
        raise ValueError("PDF rules require a fixed 10-chip big blind")
    deck = _deck_or_shuffle(deck)

    # Deal alternating cards, starting with the button.
    hole_cards = _deal_hole_cards(deck, "A")
    chips = 500 if ruleset == "pdf" else 20 * bet_unit
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
        ruleset=ruleset,
    )


def _increment(state: GameState) -> int:
    if state.ruleset == "pdf" and state.phase in ("turn", "river"):
        return 20
    return state.bet_unit


def _can_raise_or_bet(state: GameState, player: Player, payment: int) -> bool:
    own = _index(player)
    if state.stacks[own] <= payment:
        return False
    if state.ruleset != "pdf":
        return True
    target = state.contributions[own] + payment
    opponent = _index(_other(player))
    return state.stacks[opponent] > target - state.contributions[opponent]


def legal_actions(state: GameState, player: Player) -> frozenset[Action]:
    """Return only actions the current player can afford and perform."""

    if player not in ("A", "B"):
        return frozenset()
    if state.phase in ("showdown", "finished"):
        if state.match_winner is None and not state.ready_players[_index(player)]:
            return frozenset({"ready"})
        return frozenset()
    if state.actor != player:
        return frozenset()

    own = _index(player)
    owed = max(state.contributions) - state.contributions[own]
    stack = state.stacks[own]
    actions: set[Action] = {"fold"}
    if owed:
        if stack > owed:
            actions.add("call")
        if state.raise_count < (
            3 if state.ruleset == "pdf" else 2
        ) and _can_raise_or_bet(state, player, owed + _increment(state)):
            actions.add("raise")
    else:
        actions.add("check")
        if _can_raise_or_bet(state, player, _increment(state)):
            if state.big_blind_option and state.phase == "preflop":
                if state.raise_count < (3 if state.ruleset == "pdf" else 2):
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


def _match_winner(state: GameState, stacks: tuple[int, int]) -> Player | None:
    if state.ruleset == "pdf":
        next_button = _other(state.button)
        required_a = 5 if next_button == "A" else 10
        required_b = 5 if next_button == "B" else 10
    else:
        required_a = required_b = state.bet_unit
    if stacks[0] <= required_a:
        return "B"
    if stacks[1] <= required_b:
        return "A"
    return None


def _finish_hand(
    state: GameState,
    stacks: tuple[int, int],
    phase: Literal["showdown", "finished"],
    winner: Player | None,
) -> GameState:
    return replace(
        state,
        stacks=stacks,
        pot=0,
        contributions=(0, 0),
        phase=phase,
        actor=None,
        raise_count=0,
        checks_in_row=0,
        big_blind_option=False,
        winner=winner,
        match_winner=_match_winner(state, stacks),
        ready_players=(False, False),
    )


def _showdown(state: GameState) -> GameState:
    if len(state.board) != 5:
        raise ValueError("showdown requires five community cards")
    evaluator = Evaluator()
    scores = tuple(
        evaluator.evaluate(
            [Card.new(card) for card in hand],
            [Card.new(card) for card in state.board],
        )
        for hand in state.hole_cards
    )
    stacks = list(state.stacks)
    if scores[0] < scores[1]:
        winner: Player | None = "A"
        stacks[0] += state.pot
    elif scores[1] < scores[0]:
        winner = "B"
        stacks[1] += state.pot
    else:
        winner = None
        stacks[0] += state.pot // 2
        stacks[1] += state.pot // 2
        odd_chip_seat = _other(state.button) if state.ruleset == "pdf" else state.button
        stacks[_index(odd_chip_seat)] += state.pot % 2
    return _finish_hand(state, (stacks[0], stacks[1]), "showdown", winner)


def _start_next_hand(state: GameState, deck: tuple[str, ...]) -> GameState:
    button = _other(state.button)
    small_blind = state.bet_unit // 2
    big_blind = state.bet_unit
    stacks = list(state.stacks)
    stacks[_index(button)] -= small_blind
    stacks[_index(_other(button))] -= big_blind
    contributions = [0, 0]
    contributions[_index(button)] = small_blind
    contributions[_index(_other(button))] = big_blind
    return replace(
        state,
        button=button,
        stacks=(stacks[0], stacks[1]),
        contributions=(contributions[0], contributions[1]),
        pot=small_blind + big_blind,
        hole_cards=_deal_hole_cards(deck, button),
        board=(),
        deck=deck[4:],
        burn_cards=(),
        phase="preflop",
        actor=button,
        raise_count=0,
        checks_in_row=0,
        big_blind_option=True,
        winner=None,
        match_winner=None,
        ready_players=(False, False),
        hand_number=state.hand_number + 1,
    )


def _advance_round(state: GameState) -> GameState:
    phase = _NEXT_PHASE[state.phase]
    if phase == "showdown":
        return _showdown(state)
    count = 3 if phase == "flop" else 1
    burn = 1 if state.ruleset == "pdf" else 0
    return replace(
        state,
        phase=phase,
        actor=_other(state.button),
        board=state.board + state.deck[burn : burn + count],
        deck=state.deck[burn + count :],
        burn_cards=state.burn_cards + state.deck[:burn],
        contributions=(0, 0),
        raise_count=0,
        checks_in_row=0,
        big_blind_option=False,
    )


def apply_action(
    state: GameState,
    player: Player,
    action: str,
    *,
    deck: tuple[str, ...] | None = None,
) -> ActionResult:
    """Apply one move, leaving the original state untouched on success or failure.

    The transport layer should call this only after authenticating the player.
    It should use ``accepted`` and ``error`` to form its reply, and retain
    ``state`` as the next authoritative state only when accepted is true.
    """

    if action not in legal_actions(state, player):
        return ActionResult(False, state, "illegal action or wrong turn")
    if deck is not None and action != "ready":
        return ActionResult(False, state, "deck is only used for the next hand")

    if action == "ready":
        ready = list(state.ready_players)
        ready[_index(player)] = True
        if not all(ready):
            if deck is not None:
                return ActionResult(False, state, "deck is only used for the next hand")
            return ActionResult(
                True, replace(state, ready_players=(ready[0], ready[1]))
            )
        try:
            next_deck = _deck_or_shuffle(deck)
        except ValueError as exc:
            return ActionResult(False, state, str(exc))
        return ActionResult(True, _start_next_hand(state, next_deck))

    if action == "fold":
        winner = _other(player)
        chips = state.stacks[_index(winner)] + state.pot
        return ActionResult(
            True,
            _finish_hand(
                state,
                _set_pair(state.stacks, winner, chips),
                "finished",
                winner,
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
        paid = _pay(state, player, _increment(state))
        return ActionResult(
            True,
            replace(paid, actor=_other(player), checks_in_row=0),
        )
    # The remaining legal action is raise.
    paid = _pay(state, player, owed + _increment(state))
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
