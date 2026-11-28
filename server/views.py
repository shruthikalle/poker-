"""Build an explicit JSON view for a single authenticated seat."""

from poker.engine import Player, legal_actions
from poker.rooms import Room

from .timers import SEATS, Timing


def player_view(
    room: Room, seat: Player, revision: int, timing: Timing | None = None, now: int = 0
) -> dict[str, object]:
    hand = room.hand
    view: dict[str, object] = {
        "type": "snapshot",
        "status": room.status,
        "seat": seat,
        "bet_unit": room.bet_unit,
        "revision": revision,
    }
    if timing is not None:
        view.update(timing_view(room, timing, now))
        if timing.terminal_at is not None:
            view["room_release"] = {
                "acknowledged": {
                    player: player in timing.acknowledged for player in SEATS
                },
                "eligible": timing.can_release(now),
                "remaining_ms": _milliseconds(timing.retention_remaining(now)),
            }
    if hand is None:
        return view

    index = 0 if seat == "A" else 1
    actions = legal_actions(hand, seat)
    if timing is not None and (timing.result is not None or not all(timing.presence)):
        actions = frozenset()
    result = None
    if hand.phase == "showdown" and hand.pot == 0:
        result = {
            "kind": "showdown_tie" if hand.winner is None else "showdown_win",
            "winner": hand.winner,
        }
        if timing is None or timing.result is None or timing.result.reason == "engine":
            result["showdown_hole_cards"] = {
                "A": list(hand.hole_cards[0]),
                "B": list(hand.hole_cards[1]),
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
        match_winner=timing.result.winner
        if timing is not None and timing.result is not None
        else hand.match_winner,
    )
    if hand.ruleset == "pdf":
        view["bet_increment"] = 20 if hand.phase in ("turn", "river") else 10
    return view


def _milliseconds(nanoseconds: int) -> int:
    return (max(0, nanoseconds) + 999_999) // 1_000_000


def timing_view(room: Room, timing: Timing, now: int) -> dict[str, object]:
    hand = room.hand
    if timing.result is not None:
        lifecycle = "complete"
    elif hand is None:
        lifecycle = "waiting"
    elif not timing.activated:
        lifecycle = "awaiting_players"
    elif not all(timing.presence):
        lifecycle = "paused"
    elif hand.actor is None:
        lifecycle = "between_hands"
    else:
        lifecycle = "active"
    clock_status, remaining = "inactive", None
    if timing.turn_deadline is not None:
        clock_status, remaining = "running", _milliseconds(timing.turn_deadline - now)
    elif timing.saved_turn is not None:
        clock_status, remaining = "paused", _milliseconds(timing.saved_turn)
    automatic = timing.last_automatic_action
    return {
        "lifecycle": lifecycle,
        "lifecycle_revision": timing.revision,
        "presence": dict(zip(SEATS, timing.presence)),
        "turn_clock": {
            "status": clock_status,
            "acting_player": hand.actor
            if hand is not None and remaining is not None
            else None,
            "remaining_ms": remaining,
        },
        "disconnect_grace": {
            seat: {"remaining_ms": _milliseconds(deadline - now)}
            if deadline is not None
            else None
            for seat, deadline in zip(SEATS, timing.grace)
        },
        "match_result": (
            {"reason": timing.result.reason, "winner": timing.result.winner}
            if timing.result is not None
            else None
        ),
        "last_automatic_action": (
            {
                "source": "server",
                "reason": "turn_timeout",
                "hand_id": automatic.hand_id,
                "seat": automatic.seat,
                "action": automatic.action,
            }
            if automatic is not None
            else None
        ),
    }
