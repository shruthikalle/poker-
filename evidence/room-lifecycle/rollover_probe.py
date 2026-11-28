"""Observe the room allocation boundary after a terminal match on loopback."""

import argparse
import json
from secrets import token_hex
from time import monotonic

from httpx2 import Client
from websockets.exceptions import ConnectionClosed
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


def snapshot(socket, lifecycle, *, eligible=False):
    deadline = monotonic() + 10
    while (remaining := deadline - monotonic()) > 0:
        frame = json.loads(socket.recv(timeout=remaining))
        if (
            frame.get("type") == "snapshot"
            and frame["lifecycle"] == lifecycle
            and (not eligible or frame.get("room_release", {}).get("eligible"))
        ):
            return frame
    raise AssertionError(f"did not receive a {lifecycle} snapshot")


def terminal_accounting(frame):
    return {key: frame[key] for key in ("match_result", "hand_id", "stacks", "pot")}


def verify_release(client, ws_url, a, b, host, create_key, join_key):
    for socket in (a, b):
        socket.send('{"type":"acknowledge_result"}')
    snapshot(a, "complete", eligible=True)
    assert client.post("/api/rooms", json={"bet_unit": 10}).status_code == 409
    a.send('{"type":"release_room"}')
    for socket in (a, b):
        try:
            while True:
                socket.recv(timeout=3)
        except ConnectionClosed as closed:
            assert closed.rcvd is not None and closed.rcvd.code == 4001
    print(
        "Explicit release -> close 4001 for both seats; acknowledgment alone retained the room"
    )
    retries = (
        client.post("/api/rooms", json={"bet_unit": 10}, headers=create_key),
        client.post(
            "/api/rooms/join", json={"room_code": host["room_code"]}, headers=join_key
        ),
    )
    assert all(
        retry.status_code == 409 and retry.json() == {"detail": "ADMISSION_EXPIRED"}
        for retry in retries
    )
    print("Original create and join retry -> 409 ADMISSION_EXPIRED")
    assert (
        client.get(
            "/api/session", headers={"Authorization": f"Bearer {host['session_token']}"}
        ).status_code
        == 401
    )
    context = client.get("/api/admission-context").json()["context"]
    created = client.post("/api/rooms", json={"bet_unit": 10}, headers=scoped(context))
    assert created.status_code == 201, created.status_code
    fresh = created.json()
    assert (
        fresh["room_code"] != host["room_code"]
        and fresh["session_token"] != host["session_token"]
    )
    joined = client.post(
        "/api/rooms/join",
        json={"room_code": fresh["room_code"]},
        headers=scoped(context),
    )
    assert joined.status_code == 200, joined.status_code
    with (
        connect(ws_url, proxy=None, open_timeout=3) as new_a,
        connect(ws_url, proxy=None, open_timeout=3) as new_b,
    ):
        authenticate(new_a, fresh)
        authenticate(new_b, joined.json())
        initial = snapshot(new_a, "active")
        assert initial["revision"] == initial["hand_id"] == 1
        assert initial["stacks"] == {"A": 495, "B": 490} and initial["pot"] == 15
        assert initial["match_result"] is None and "room_release" not in initial
        print(
            f"Fresh admission in the same process -> 201/200; hand {initial['hand_id']}, revision {initial['revision']}, A/B 495/490 + pot 15"
        )


def scoped(context):
    return {"Admission-Key": f"{context}.{token_hex(32)}"}


def probe(port, release):
    ws_url = f"ws://127.0.0.1:{port}/ws"
    with Client(
        base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5
    ) as client:
        context = (
            client.get("/api/admission-context").json()["context"] if release else None
        )
        create_key, join_key = (
            (scoped(context), scoped(context)) if release else (None, None)
        )
        created = client.post("/api/rooms", json={"bet_unit": 10}, headers=create_key)
        assert created.status_code == 201, created.status_code
        host = created.json()
        joined = client.post(
            "/api/rooms/join", json={"room_code": host["room_code"]}, headers=join_key
        )
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
                if release:
                    verify_release(client, ws_url, a, b, host, create_key, join_key)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--release",
        action="store_true",
        help="also exercise the final PDF room release contract",
    )
    args = parser.parse_args()
    probe(args.port, args.release)
