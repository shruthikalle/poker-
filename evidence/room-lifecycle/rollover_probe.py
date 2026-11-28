"""Observe the room allocation boundary after a terminal match on loopback."""

import argparse
import json
from time import monotonic

from httpx2 import Client
from websockets.sync.client import connect


def authenticate(socket, admission):
    socket.send(
        json.dumps(
            {
                "type": "auth",
                "protocol": "gameplay.v1",
                "token": admission["session_token"],
            }
        )
    )


def snapshot(socket, lifecycle):
    deadline = monotonic() + 10
    while (remaining := deadline - monotonic()) > 0:
        frame = json.loads(socket.recv(timeout=remaining))
        if frame.get("type") == "snapshot" and frame["lifecycle"] == lifecycle:
            return frame
    raise AssertionError(f"did not receive a {lifecycle} snapshot")


def terminal_accounting(frame):
    return {key: frame[key] for key in ("match_result", "hand_id", "stacks", "pot")}


def probe(port):
    ws_url = f"ws://127.0.0.1:{port}/ws"
    with Client(
        base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5
    ) as client:
        created = client.post("/api/rooms", json={"bet_unit": 10})
        assert created.status_code == 201, created.status_code
        host = created.json()
        joined = client.post("/api/rooms/join", json={"room_code": host["room_code"]})
        assert joined.status_code == 200, joined.status_code
        guest = joined.json()
        assert host["seat"] == "A" and guest["seat"] == "B"
        assert host["session_token"] != guest["session_token"]
        print("POST /api/rooms -> 201; POST /api/rooms/join -> 200; two distinct seats")

        with connect(ws_url, proxy=None, open_timeout=3) as a:
            authenticate(a, host)
            with connect(ws_url, proxy=None, open_timeout=3) as b:
                authenticate(b, guest)
                guest_active = snapshot(b, "active")
                active = snapshot(a, "active")
                assert active["hand_id"] == guest_active["hand_id"] == 1
                assert active["pot"] == guest_active["pot"] == 15
                assert active["own_hole_cards"] != guest_active["own_hole_cards"]
                print("Both authenticated seats observed hand 1 in play")

            terminal = snapshot(a, "complete")
            summary = terminal_accounting(terminal)
            assert summary["match_result"] == {"reason": "forfeit", "winner": "A"}
            assert terminal["stacks"] == active["stacks"]
            assert terminal["pot"] == active["pot"]
            assert terminal["legal_actions"] == [] and not terminal["can_ready"]
            assert terminal["board"] == [] and terminal["result"] is None
            assert terminal["own_hole_cards"] == active["own_hole_cards"]
            assert not set(guest_active["own_hole_cards"]) & set(
                terminal["own_hole_cards"]
            )
            print(f"Terminal snapshot: {json.dumps(summary, sort_keys=True)}")

            fresh = client.post("/api/rooms", json={"bet_unit": 10})
            assert fresh.status_code == 409, fresh.status_code
            assert fresh.json() == {"detail": "an active room already exists"}
            print(f"POST /api/rooms after terminal -> 409 {fresh.text}")

        with connect(ws_url, proxy=None, open_timeout=3) as b:
            authenticate(b, guest)
            observed = snapshot(b, "complete")
            assert terminal_accounting(observed) == summary
            assert observed["own_hole_cards"] == guest_active["own_hole_cards"]
            assert observed["result"] is None
            print(
                "Returning seat B observed the same terminal result and its own cards"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    probe(parser.parse_args().port)
