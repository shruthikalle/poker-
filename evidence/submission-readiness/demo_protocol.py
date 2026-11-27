"""Show a wrong-turn rejection and a real disconnect on a fresh fixture server."""

import argparse
import json
import sys
from pathlib import Path
from time import monotonic, sleep

from httpx2 import Client
from websockets.sync.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deepthi-day-2"))
from smoke import ack, authenticate, command, receive  # noqa: E402


def public(snapshot):
    return snapshot["revision"], snapshot["actor"], snapshot["stacks"], snapshot["pot"]


def sample(socket):
    socket.send(json.dumps({"type": "snapshot_request"}))
    frame = receive(socket)
    assert frame["type"] == "snapshot"
    return frame


def rehearse(base):
    with Client() as http:
        host = http.post(f"{base}/api/rooms", json={"bet_unit": 10})
        assert host.status_code == 201
        host = host.json()
        guest = http.post(
            f"{base}/api/rooms/join", json={"room_code": host["room_code"]}
        )
        assert guest.status_code == 200
        guest = guest.json()

    url = "ws" + base.removeprefix("http") + "/ws"
    with connect(url) as a:
        authenticate(a, host["session_token"])
        assert receive(a)["lifecycle"] == "awaiting_players"
        with connect(url) as b:
            authenticate(b, guest["session_token"])
            initial = receive(a)
            peer = receive(b)
            expected = (1, "A", {"A": 195, "B": 190}, 15)
            assert public(initial) == public(peer) == expected
            assert initial["own_hole_cards"] == ["9h", "5h"]
            assert peer["own_hole_cards"] == ["Ts", "3c"]
            assert all(card not in json.dumps(initial) for card in ("Ts", '"3c"'))
            print("Before: revision 1, actor A, stacks 195/190, pot 15", flush=True)
            denial = ack(b, command("wrong-seat-fold", "fold", 1), 1, "WRONG_TURN")
            assert public(sample(a)) == public(sample(b)) == expected
            print(
                f"B tries fold: {denial['error_code']}. After: revision 1, actor A, stacks 195/190, pot 15",
                flush=True,
            )
            end = monotonic() + 4
            while sample(a)["turn_clock"]["remaining_ms"] > 28_000:
                assert monotonic() < end, "the active turn did not count down"
                sleep(0.1)
        paused = receive(a)
        assert paused["lifecycle"] == "paused" and public(paused) == expected
        saved = paused["turn_clock"]["remaining_ms"]
        assert 0 < saved <= 28_000
        with connect(url) as successor:
            authenticate(successor, guest["session_token"])
            resumed = receive(a)
            restored = receive(successor)
            assert resumed["lifecycle"] == "active"
            assert public(resumed) == public(restored) == expected
            assert restored["seat"] == "B" and restored["own_hole_cards"] == [
                "Ts",
                "3c",
            ]
            remaining = resumed["turn_clock"]["remaining_ms"]
            assert 0 < remaining <= saved
            print(
                f"B reconnects as B. A turn paused at {saved} ms, resumed at {remaining} ms; revision 1, pot 15",
                flush=True,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    rehearse(parser.parse_args().url.rstrip("/"))
