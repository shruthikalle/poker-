"""Seeded PDF-rule hands with independent state invariants after every move."""

import argparse
import json
from random import Random

from poker.engine import GameState, apply_action, legal_actions, new_game

CARDS = tuple(f"{rank}{suit}" for rank in "23456789TJQKA" for suit in "cdhs")
BOARD_LENGTH = {"preflop": 0, "flop": 3, "turn": 4, "river": 5, "showdown": 5}


def shuffled_deck(random: Random) -> tuple[str, ...]:
    cards = list(CARDS)
    random.shuffle(cards)
    return tuple(cards)


def check(state: GameState) -> None:
    cards = (
        *state.hole_cards[0],
        *state.hole_cards[1],
        *state.burn_cards,
        *state.board,
        *state.deck,
    )
    assert len(cards) == 52 and set(cards) == set(CARDS), "cards lost or duplicated"
    assert sum(state.stacks) + state.pot == 1000, "chip supply changed"
    assert min(*state.stacks, *state.contributions, state.pot) >= 0, "negative chips"
    assert state.ruleset == "pdf" and state.bet_unit == 10, "wrong rule variant"
    assert state.raise_count <= 3, "raise cap exceeded"
    if state.phase in {"showdown", "finished"}:
        assert state.actor is None and state.pot == 0, "settled hand remains active"
        assert state.contributions == (0, 0), "settled commitments remain"
        assert len(state.board) in {0, 3, 4, 5}, "invalid finished board"
    else:
        assert state.actor in {"A", "B"}, "active hand has no actor"
        assert len(state.board) == BOARD_LENGTH[state.phase], "wrong board length"
        assert (
            len(state.burn_cards)
            == {"preflop": 0, "flop": 1, "turn": 2, "river": 3}[state.phase]
        ), "wrong burn count"
        assert state.pot >= sum(state.contributions), "street commitments exceed pot"


def accepted(state: GameState, seat: str, action: str, *, deck=None) -> GameState:
    result = apply_action(state, seat, action, deck=deck)
    assert result.accepted, (seat, action, result.error)
    check(result.state)
    return result.state


def run_seed(seed: int, hand_target: int) -> dict[str, int]:
    random = Random(seed)
    state = new_game(deck=shuffled_deck(random))
    check(state)
    hands = actions = showdowns = folds = matches = 0
    recent: list[str] = []
    try:
        while hands < hand_target:
            assert actions < hand_target * 30, "step limit reached"
            actor = state.actor
            assert actor is not None
            choices = sorted(legal_actions(state, actor))
            assert choices
            weights = [
                1 if move == "fold" else 4 if move in {"check", "call"} else 3
                for move in choices
            ]
            move = random.choices(choices, weights=weights)[0]
            recent.append(f"hand={state.hand_number} {state.phase} {actor}:{move}")
            recent = recent[-30:]
            state = accepted(state, actor, move)
            actions += 1
            if state.phase not in {"showdown", "finished"}:
                continue

            hands += 1
            showdowns += state.phase == "showdown"
            folds += state.phase == "finished"
            if state.match_winner is not None:
                matches += 1
                if hands < hand_target:
                    state = new_game(deck=shuffled_deck(random))
                    check(state)
                continue
            if hands < hand_target:
                state = accepted(state, "A", "ready")
                state = accepted(state, "B", "ready", deck=shuffled_deck(random))
                actions += 2
    except AssertionError as error:
        raise AssertionError(
            f"seed={seed}, hands={hands}, recent={recent}: {error}"
        ) from error
    return {
        "seed": seed,
        "hands": hands,
        "actions": actions,
        "showdowns": showdowns,
        "folds": folds,
        "completed_matches": matches,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hands-per-seed", type=int, default=250)
    parser.add_argument("--seeds", type=int, nargs="+", default=[11, 29, 47, 83])
    args = parser.parse_args()
    if args.hands_per_seed < 1 or len(set(args.seeds)) != len(args.seeds):
        parser.error("provide a positive hand count and distinct seeds")
    runs = [run_seed(seed, args.hands_per_seed) for seed in args.seeds]
    print(
        json.dumps(
            {
                "ruleset": "pdf",
                "runs": runs,
                "totals": {
                    field: sum(run[field] for run in runs)
                    for field in (
                        "hands",
                        "actions",
                        "showdowns",
                        "folds",
                        "completed_matches",
                    )
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
