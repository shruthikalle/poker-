"""Exercise a deterministic full hand through a live local Uvicorn server."""

import argparse
import json

from httpx2 import Client
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from server.fixtures import fixed_deck

HTTP = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000/ws"
HAND_FIELDS = {
    "type",
    "status",
    "seat",
    "bet_unit",
    "revision",
    "hand_id",
    "phase",
    "actor",
    "button",
    "stacks",
    "contributions",
    "pot",
    "board",
    "raise_count",
    "own_hole_cards",
    "legal_actions",
    "ready_seats",
    "can_ready",
    "result",
    "match_winner",
}
ACK_FIELDS = {
    "type",
    "hand_id",
    "action_id",
    "outcome_revision",
    "accepted",
    "error_code",
}
PRIVATE_FIELDS = {"seat", "own_hole_cards", "can_ready", "legal_actions"}
ACTORS = ("A", "B", "B", "A", "B", "A", "B", "A")
PHASES = ("preflop", "flop", "flop", "turn", "turn", "river", "river", "showdown")


def receive(socket):
    try:
        return json.loads(socket.recv(timeout=3))
    except ConnectionClosed as exc:
        code = exc.rcvd.code if exc.rcvd is not None else "none"
        raise AssertionError(
            f"expected gameplay payload, socket closed with {code}"
        ) from None
    except TimeoutError:
        raise AssertionError(
            "gameplay payload did not arrive within 3 seconds"
        ) from None


def authenticate(socket, credential):
    socket.send(
        json.dumps({"type": "auth", "token": credential, "protocol": "gameplay.v1"})
    )


def command(action_id, action, revision):
    return {
        "type": "action",
        "action_id": action_id,
        "hand_id": 1,
        "expected_revision": revision,
        "action": action,
    }


def ack(socket, request, revision, error=None):
    socket.send(json.dumps(request))
    received = receive(socket)
    assert set(received) == ACK_FIELDS, "unexpected acknowledgment fields"
    assert received == {
        "type": "action_ack",
        "hand_id": 1,
        "action_id": request["action_id"],
        "outcome_revision": revision,
        "accepted": error is None,
        "error_code": error,
    }, "unexpected acknowledgment outcome"
    return received


def views(sockets, deck, revision, phase, stacks, pot):
    messages = {seat: receive(socket) for seat, socket in sockets.items()}
    count = {
        "preflop": 0,
        "flop": 3,
        "turn": 4,
        "river": 5,
        "showdown": 5,
        "finished": 0,
    }[phase]
    own = {"A": [deck[0], deck[2]], "B": [deck[1], deck[3]]}
    public = []
    for seat, message in messages.items():
        assert set(message) == HAND_FIELDS, "snapshot contains unexpected fields"
        assert (
            message["type"],
            message["seat"],
            message["revision"],
            message["phase"],
        ) == (
            "snapshot",
            seat,
            revision,
            phase,
        ), "unexpected snapshot header"
        assert (message["stacks"], message["pot"]) == (
            dict(zip(("A", "B"), stacks)),
            pot,
        )
        assert sum(message["stacks"].values()) + message["pot"] == 400, "chips changed"
        assert message["board"] == list(deck[4 : 4 + count]), "incorrect revealed board"
        assert message["own_hole_cards"] == own[seat], "incorrect private cards"
        forbidden = list(deck[4 + count :])
        if phase != "showdown":
            forbidden += own["B" if seat == "A" else "A"]
        encoded = json.dumps(message)
        assert all(json.dumps(card) not in encoded for card in forbidden), (
            "private card leaked"
        )
        public.append(
            {key: value for key, value in message.items() if key not in PRIVATE_FIELDS}
        )
    assert public[0] == public[1], "players see different public state"
    print(f"revision {revision} {phase}: A/B {stacks[0]}/{stacks[1]}, pot {pot}")
    return public[0]


def run_hand(sockets, deck, scenario):
    initial = views(sockets, deck, 1, "preflop", (195, 190), 15)
    assert initial["contributions"] == {"A": 5, "B": 10}
    a, b = sockets["A"], sockets["B"]

    if scenario == "fold":
        ack(a, command("fold", "fold", 1), 2)
        result = views(sockets, deck, 2, "finished", (195, 205), 0)["result"]
        assert result == {"kind": "fold_win", "winner": "B"}, "incorrect fold result"
        return

    call = command("call", "call", 1)
    recorded = ack(a, call, 2)
    views(sockets, deck, 2, "preflop", (190, 190), 20)
    assert ack(a, call, 2) == recorded
    ack(a, {**call, "action": "fold"}, 2, "REPLAY_CONFLICT")
    ack(b, command("stale", "check", 1), 2, "STALE_REVISION")
    assert receive(b)["revision"] == 2, (
        "stale command did not receive recovery snapshot"
    )
    ack(a, command("wrong-turn", "fold", 2), 2, "WRONG_TURN")
    print("replay, conflict, stale revision, and wrong turn verified at revision 2")

    for revision, (seat, phase) in enumerate(zip(ACTORS[1:], PHASES[1:]), 2):
        request = command(f"check-{revision}", "check", revision)
        outcome = ack(sockets[seat], request, revision + 1)
        final = phase == "showdown"
        stacks = (200, 200) if scenario == "tie" else (210, 190)
        current = views(
            sockets,
            deck,
            revision + 1,
            phase,
            stacks if final else (190, 190),
            0 if final else 20,
        )
    expected = ("showdown_tie", None) if scenario == "tie" else ("showdown_win", "A")
    result = current["result"]
    assert (result["kind"], result["winner"]) == expected, "incorrect showdown result"
    assert result["showdown_hole_cards"] == {
        "A": [deck[0], deck[2]],
        "B": [deck[1], deck[3]],
    }
    assert ack(a, request, 9) == outcome, "settlement replay changed original outcome"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario", choices=("showdown", "fold", "tie"), default="showdown"
    )
    scenario = parser.parse_args().scenario
    deck = fixed_deck(scenario)
    with Client(base_url=HTTP, timeout=3, trust_env=False) as client:
        health = client.get("/health")
        assert health.status_code == 200 and health.json() == {"status": "ok"}
        created = client.post("/api/rooms", json={"bet_unit": 10})
        assert created.status_code == 201
        host = created.json()
        with connect(WS, proxy=None, open_timeout=3, close_timeout=1) as a:
            authenticate(a, host["session_token"])
            waiting = receive(a)
            assert waiting == {
                "type": "snapshot",
                "status": "waiting",
                "seat": "A",
                "bet_unit": 10,
                "revision": 0,
            }, (
                f"expected waiting snapshot, received {waiting.get('type')} ({waiting.get('code')})"
            )
            print("A authenticated and waiting at revision 0")
            joined = client.post(
                "/api/rooms/join", json={"room_code": host["room_code"]}
            )
            assert joined.status_code == 200
            guest = joined.json()
            assert guest["session_token"] != host["session_token"]
            with connect(WS, proxy=None, open_timeout=3, close_timeout=1) as b:
                authenticate(b, guest["session_token"])
                run_hand({"A": a, "B": b}, deck, scenario)
    print(f"{scenario} gameplay smoke passed")


if __name__ == "__main__":
    main()
