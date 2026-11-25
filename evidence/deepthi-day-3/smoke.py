"""Verify timeout and recovery using two real loopback WebSocket clients."""

import argparse
import json
from contextlib import ExitStack
from time import monotonic, sleep

from httpx2 import Client
from websockets.sync.client import connect

HTTP = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000/ws"
CARDS = {"A": ["9h", "5h"], "B": ["Ts", "3c"]}


def receive(socket):
    try:
        return json.loads(socket.recv(timeout=4))
    except TimeoutError:
        raise AssertionError("expected gameplay frame within four seconds") from None


def auth(stack, token):
    socket = stack.enter_context(
        connect(WS, proxy=None, open_timeout=3, close_timeout=1)
    )
    socket.send(json.dumps({"type": "auth", "token": token, "protocol": "gameplay.v1"}))
    return socket


def command(socket, name, revision, move="call"):
    socket.send(
        json.dumps(
            {
                "type": "action",
                "action_id": name,
                "hand_id": 1,
                "expected_revision": revision,
                "action": move,
            }
        )
    )


def check_private(view, seat):
    assert view["own_hole_cards"] == CARDS[seat], "incorrect private cards"
    hidden = CARDS["B" if seat == "A" else "A"]
    encoded = json.dumps(view)
    assert all(json.dumps(card) not in encoded for card in hidden), (
        "opponent card leaked"
    )
    assert "deck" not in view and "token" not in view, "private field leaked"
    assert sum(view["stacks"].values()) + view["pot"] == 400, "chip total changed"


def start(stack, client):
    assert client.get("/health").json() == {"status": "ok"}
    created = client.post("/api/rooms", json={"bet_unit": 10})
    assert created.status_code == 201
    host = created.json()
    a = auth(stack, host["session_token"])
    assert receive(a)["lifecycle"] == "waiting"
    joined = client.post("/api/rooms/join", json={"room_code": host["room_code"]})
    assert joined.status_code == 200
    guest = joined.json()
    assert guest["session_token"] != host["session_token"]
    assert receive(a)["lifecycle"] == "awaiting_players"
    b = auth(stack, guest["session_token"])
    a_view, b_view = receive(a), receive(b)
    for seat, view in (("A", a_view), ("B", b_view)):
        check_private(view, seat)
        assert view["presence"] == {"A": True, "B": True}
        assert view["turn_clock"]["status"] == "running"
        assert view["stacks"] == {"A": 195, "B": 190} and view["pot"] == 15
    assert a_view["turn_clock"] == b_view["turn_clock"]
    return a, b, host["session_token"], guest["session_token"], a_view


def timeout_scenario(a, b, *, check):
    if check:
        command(a, "call-first", 1)
        assert receive(a)["accepted"]
        assert receive(a)["revision"] == receive(b)["revision"] == 2
    observed = receive(a), receive(b)
    for seat, view in zip(("A", "B"), observed):
        check_private(view, seat)
        move = "check" if check else "fold"
        assert view["last_automatic_action"] == {
            "source": "server",
            "reason": "turn_timeout",
            "hand_id": 1,
            "seat": "B" if check else "A",
            "action": move,
        }
        if check:
            assert (view["phase"], view["actor"], view["pot"]) == ("flop", "B", 20)
            assert view["stacks"] == {"A": 190, "B": 190}
        else:
            assert view["result"] == {"kind": "fold_win", "winner": "B"}
            assert view["stacks"] == {"A": 195, "B": 205} and view["pot"] == 0
    print(
        "automatic B check: flop, A/B 190/190, pot 20"
        if check
        else "automatic A fold: B wins hand, A/B 195/205, pot 0"
    )


def reconnect_scenario(stack, a, b, a_token, initial):
    # Let some active time elapse using a sampled server clock, with a bounded wait.
    limit = monotonic() + 1.5
    current = initial
    while current["turn_clock"]["remaining_ms"] > 1500 and monotonic() < limit:
        sleep(0.025)
        a.send('{"type":"snapshot_request"}')
        current = receive(a)
    assert current["turn_clock"]["remaining_ms"] <= 1500, "clock did not decrement"
    a.close()
    paused = receive(b)
    assert paused["presence"] == {"A": False, "B": True}
    saved = paused["turn_clock"]["remaining_ms"]
    assert paused["turn_clock"]["status"] == "paused" and 0 < saved <= 1500
    a = auth(stack, a_token)
    a_view, b_view = receive(a), receive(b)
    check_private(a_view, "A")
    check_private(b_view, "B")
    for view in (a_view, b_view):
        assert view["lifecycle"] == "active"
        assert view["turn_clock"]["remaining_ms"] == saved, "resume reset the clock"
    command(a, "call-after-return", 1)
    assert receive(a)["accepted"]
    assert receive(a)["pot"] == receive(b)["pot"] == 20
    print(
        "disconnect paused the turn; reconnect restored exactly the sampled saved time"
    )
    print("A retained private cards and a legal call advanced both views to pot 20")


def terminal_view(view, seat, outcome):
    check_private(view, seat)
    assert view["lifecycle"] == "complete" and view["match_result"] == outcome
    assert view["result"] is None and view["pot"] == 15
    assert view["turn_clock"]["status"] == "inactive"
    assert view["disconnect_grace"] == {"A": None, "B": None}
    assert view["legal_actions"] == [] and view["can_ready"] is False


def terminal_scenario(stack, a, b, a_token, *, both):
    a.close()
    paused = receive(b)
    assert paused["lifecycle"] == "paused"
    if both:
        b.close()
        # With no sockets present, wait past the internal one-second grace.
        sleep(1.2)
        outcome = {"reason": "both_absent", "winner": None}
    else:
        outcome = {"reason": "forfeit", "winner": "B"}
        terminal_view(receive(b), "B", outcome)
    a = auth(stack, a_token)
    terminal_view(receive(a), "A", outcome)
    command(a, "late", 1)
    assert receive(a)["error_code"] == "MATCH_COMPLETE"
    print(f"{outcome['reason']}: winner={outcome['winner']}, stacks and pot preserved")
    print(
        "late authenticated observation retained privacy and could not reopen the match"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        required=True,
        choices=(
            "timeout-fold",
            "timeout-check",
            "reconnect",
            "forfeit",
            "both-absent",
        ),
    )
    scenario = parser.parse_args().scenario
    with ExitStack() as stack:
        client = stack.enter_context(Client(base_url=HTTP, timeout=3, trust_env=False))
        a, b, a_token, _, initial = start(stack, client)
        if scenario.startswith("timeout-"):
            timeout_scenario(a, b, check=scenario == "timeout-check")
        elif scenario == "reconnect":
            reconnect_scenario(stack, a, b, a_token, initial)
        else:
            terminal_scenario(stack, a, b, a_token, both=scenario == "both-absent")
    print(f"{scenario} smoke passed")


if __name__ == "__main__":
    main()
