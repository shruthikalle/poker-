"""Verify mixed admission and lobby presence on an empty loopback server."""

import json

from httpx2 import Client
from websockets.exceptions import ConnectionClosedError
from websockets.sync.client import connect

HTTP = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000/ws"


def lobby(socket, seat: str, ready: bool, guest_connected: bool) -> None:
    assert json.loads(socket.recv(timeout=3)) == {
        "type": "lobby",
        "your_seat": seat,
        "table_ready": ready,
        "connected": {"A": True, "B": guest_connected},
    }


def authenticate(socket, token: str) -> None:
    socket.send(json.dumps({"type": "auth", "token": token}))


def main() -> None:
    with Client(base_url=HTTP, timeout=3, trust_env=False) as client:
        created = client.post("/api/rooms", json={"bet_unit": 12})
        assert created.status_code == 201
        room = created.json()
        assert room["seat"] == "A" and room["status"] == "waiting"
        print("POST /api/rooms -> 201 (A waiting, bet unit 12)")

        invalid = client.post("/api/join", json={"room_code": "café"})
        assert invalid.status_code == 404
        assert invalid.json() == {
            "detail": {"code": "INVALID_CODE", "message": "Table code not found"}
        }
        print("POST /api/join with unknown Unicode code -> 404")

        with connect(WS, proxy=None, open_timeout=3) as a:
            authenticate(a, room["session_token"])
            lobby(a, "A", ready=False, guest_connected=False)

            joined = client.post("/api/join", json={"room_code": room["room_code"]})
            assert joined.status_code == 201
            guest = joined.json()
            assert set(guest) == {"seat", "session_token"}
            assert (
                guest["seat"] == "B" and guest["session_token"] != room["session_token"]
            )
            lobby(a, "A", ready=True, guest_connected=False)
            print("POST /api/join -> 201 (B joins A's room, A receives lobby update)")

            identity = client.get(
                "/api/session",
                headers={"Authorization": f"Bearer {guest['session_token']}"},
            )
            assert identity.status_code == 200
            assert identity.json() == {"seat": "B", "table_ready": True}
            print("GET /api/session -> 200 (B identity only)")

            with connect(WS, proxy=None, open_timeout=3) as b:
                authenticate(b, guest["session_token"])
                lobby(a, "A", ready=True, guest_connected=True)
                lobby(b, "B", ready=True, guest_connected=True)
                with connect(WS, proxy=None, open_timeout=3) as replacement:
                    authenticate(replacement, guest["session_token"])
                    try:
                        b.recv(timeout=3)
                    except ConnectionClosedError as exc:
                        assert exc.rcvd is not None and exc.rcvd.code == 4000
                    else:
                        raise AssertionError("old lobby socket remained active")
                    lobby(a, "A", ready=True, guest_connected=True)
                    lobby(replacement, "B", ready=True, guest_connected=True)
                    replacement.send('{"type":"ping"}')
                    assert json.loads(replacement.recv(timeout=3)) == {"type": "pong"}
                    print(
                        "WebSocket B replacement -> old socket closed 4000, new socket pong"
                    )
                lobby(a, "A", ready=True, guest_connected=False)
                print("WebSocket lobby presence -> A observes B disconnect")

        full = client.post("/api/rooms/join", json={"room_code": room["room_code"]})
        assert full.status_code == 409 and full.json() == {"detail": "room is full"}
        print("POST /api/rooms/join -> 409 (shared room full)")
    print("Integration smoke checks passed")


if __name__ == "__main__":
    main()
