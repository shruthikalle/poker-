"""Build an explicit JSON view for a single authenticated seat."""

from poker.engine import Player, legal_actions
from poker.rooms import Room


def player_view(room: Room, seat: Player, revision: int) -> dict[str, object]:
    hand = room.hand
    view: dict[str, object] = {
        "type": "snapshot",
        "status": room.status,
        "seat": seat,
        "bet_unit": room.bet_unit,
        "revision": revision,
    }
    if hand is None:
        return view

    index = 0 if seat == "A" else 1
    actions = legal_actions(hand, seat)
    result = None
    if hand.phase == "showdown" and hand.pot == 0:
        result = {
            "kind": "showdown_tie" if hand.winner is None else "showdown_win",
            "winner": hand.winner,
            "showdown_hole_cards": {
                "A": list(hand.hole_cards[0]),
                "B": list(hand.hole_cards[1]),
            },
        }
    elif hand.phase == "finished":
        result = {"kind": "fold_win", "winner": hand.winner}

    view.update(
        hand_id=hand.hand_number,
        phase=hand.phase,
        button=hand.button,
        actor=hand.actor,
        stacks={"A": hand.stacks[0], "B": hand.stacks[1]},
        contributions={"A": hand.contributions[0], "B": hand.contributions[1]},
        pot=hand.pot,
        board=list(hand.board),
        raise_count=hand.raise_count,
        ready_seats={"A": hand.ready_players[0], "B": hand.ready_players[1]},
        own_hole_cards=list(hand.hole_cards[index]),
        legal_actions=sorted(actions - {"ready"}),
        can_ready="ready" in actions,
        result=result,
        match_winner=hand.match_winner,
    )
    return view
