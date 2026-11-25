"""Exercise Day 1 through a running, empty local Uvicorn server."""

import json
from argparse import ArgumentParser

from httpx2 import Client
from websockets.exceptions import ConnectionClosedError
from websockets.sync.client import connect


def check_status(response, expected: int) -> None:
    actual = response.status_code
    print(f"{response.request.method} {response.request.url.path} -> {actual}")
    assert actual == expected, f"expected HTTP {expected}, received {actual}"


def check_admission(response, seat: str, status: str) -> dict:
    admission = response.json()
    assert set(admission) == {
        "room_code",
        "seat",
        "session_token",
        "bet_unit",
        "status",
    }
    assert admission["seat"] == seat
    assert admission["status"] == status
    assert admission["bet_unit"] == 10
    assert response.headers["Cache-Control"] == "no-store"
    return admission


def check_socket(url: str, admission: dict) -> None:
    with connect(url, proxy=None, open_timeout=3) as socket:
        socket.send(
            json.dumps(
                {"type": "authenticate", "session_token": admission["session_token"]}
            )
        )
        assert json.loads(socket.recv(timeout=3)) == {
            "type": "room_status",
            "seat": admission["seat"],
            "bet_unit": 10,
            "status": admission["status"],
        }
    print(
        f"WebSocket {admission['seat']} -> {admission['status']} (status fields only)"
    )


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    port = parser.parse_args().port
    ws_url = f"ws://127.0.0.1:{port}/ws"

    with Client(
        base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=3
    ) as client:
        health = client.get("/health")
        check_status(health, 200)
        assert health.json() == {"status": "ok"}

        invalid = client.post("/api/rooms", json={"bet_unit": True})
        check_status(invalid, 422)
        assert invalid.json() == {"detail": "invalid request body"}

        created = client.post("/api/rooms", json={"bet_unit": 10})
        check_status(created, 201)
        host = check_admission(created, "A", "waiting")
        check_socket(ws_url, host)

        join_request = {"room_code": host["room_code"]}
        joined = client.post("/api/rooms/join", json=join_request)
        check_status(joined, 200)
        guest = check_admission(joined, "B", "ready")
        assert guest["room_code"] == host["room_code"]
        assert host["session_token"] != guest["session_token"]
        assert host["session_token"] not in joined.text
        check_socket(ws_url, guest)

        full = client.post("/api/rooms/join", json=join_request)
        check_status(full, 409)
        assert full.json() == {"detail": "room is full"}

    with connect(ws_url, proxy=None, open_timeout=3) as socket:
        socket.send(
            json.dumps({"type": "authenticate", "session_token": host["room_code"]})
        )
        try:
            socket.recv(timeout=3)
        except ConnectionClosedError as exc:
            assert exc.rcvd is not None
            assert exc.rcvd.code == 1008 and exc.rcvd.reason == ""
        else:
            raise AssertionError("room code received an authenticated payload")
    print("WebSocket room code -> 1008 (no application payload)")
    print("Day 1 smoke checks passed")


if __name__ == "__main__":
    main()
