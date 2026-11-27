"""Run credential-free browser acceptance scenarios against the real app."""

import argparse
import json
import socket
import sys
from contextlib import contextmanager
from pathlib import Path
from subprocess import DEVNULL, Popen, TimeoutExpired
from time import monotonic, sleep
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

HERE = Path(__file__).resolve().parent
CHECK_PATH = ("A", "B", "B", "A", "B", "A", "B", "A")


@contextmanager
def server(factory, number=None):
    if number is None:
        with socket.socket() as port:
            port.bind(("127.0.0.1", 0))
            _, number = port.getsockname()
    base = f"http://127.0.0.1:{number}"
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        f"launch:{factory}",
        "--factory",
        "--app-dir",
        str(HERE),
        "--host",
        "127.0.0.1",
        "--port",
        str(number),
        "--ws",
        "websockets-sansio",
        "--ws-max-size",
        "4096",
        "--no-access-log",
    ]
    with Popen(cmd, stdout=DEVNULL) as process:
        try:
            limit = monotonic() + 6
            while monotonic() < limit and process.poll() is None:
                try:
                    with urlopen(base + "/health", timeout=0.4) as response:
                        if response.status == 200:
                            break
                except (URLError, TimeoutError):
                    sleep(0.05)
            else:
                raise AssertionError("the fixture server did not start")
            yield base
        finally:
            process.terminate()
            try:
                process.wait(3)
            except TimeoutExpired:
                process.kill()


def wait_text(page, selector, value):
    expect(page.locator(selector)).to_have_text(value, timeout=4000)


def private_cards(page, own, forbidden=()):
    expect(page.locator("#your-cards [role=img]")).to_have_count(2)
    assert (
        page.locator("#your-cards [role=img]").evaluate_all(
            "(cards) => cards.map(card => card.getAttribute('aria-label'))"
        )
        == own
    )
    for label in forbidden:
        expect(
            page.locator("#opponent-cards").get_by_role("img", name=label, exact=True)
        ).to_have_count(0)
    assert not page.get_by_text("session_token", exact=False).count()


def observe_wire(page):
    incoming, outgoing, urls, logs = [], [], [], []

    def observe(socket):
        urls.append(socket.url)
        socket.on("framereceived", lambda payload: incoming.append(json.loads(payload)))
        socket.on("framesent", lambda payload: outgoing.append(json.loads(payload)))

    page.on("websocket", observe)
    page.on("console", lambda message: logs.append(message.text))
    return incoming, outgoing, urls, logs


def verify_wire(traces, scenario):
    credentials = {
        frame["token"]
        for _, outgoing, _, _ in traces.values()
        for frame in outgoing
        if frame["type"] == "auth"
    }
    expected = {"A": {"9h", "5h"}, "B": {"Ts", "3c"}}
    if scenario == "tie":
        expected = {"A": {"2c", "4c"}, "B": {"3d", "5d"}}
    for seat, (incoming, outgoing, urls, logs) in traces.items():
        assert urls and all(url.endswith("/ws") and "?" not in url for url in urls)
        assert all(
            token not in entry for token in credentials for entry in [*urls, *logs]
        )
        snapshots = [frame for frame in incoming if frame["type"] == "snapshot"]
        assert snapshots, "no captured authenticated snapshot traffic"
        for frame in snapshots:
            encoded = json.dumps(frame)
            assert all(token not in encoded for token in credentials)
            assert "deck" not in frame and "session_token" not in frame
            if frame.get("hand_id") != 1:
                continue
            assert set(frame["own_hole_cards"]) == expected[seat]
            shown = (frame["result"] or {}).get("showdown_hole_cards")
            if shown:
                assert frame["phase"] == "showdown"
            else:
                other = "B" if seat == "A" else "A"
                assert all(json.dumps(card) not in encoded for card in expected[other])
        if scenario == "timeout":
            assert all(frame["type"] != "action" for frame in outgoing)


def table(
    browser,
    base,
    *,
    screenshots=None,
    configure=None,
    narrow=False,
    stacks=(195, 190),
    peer_browser=None,
):
    host_context = browser.new_context(viewport={"width": 1200, "height": 900})
    guest_context = (peer_browser or browser).new_context(
        viewport={"width": 390 if narrow else 1200, "height": 900}
    )
    a, b = host_context.new_page(), guest_context.new_page()
    page_errors = []
    traces = {seat: observe_wire(page) for seat, page in (("A", a), ("B", b))}
    if configure:
        configure(a)
    for page in (a, b):
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.goto(base)
    a.get_by_label("Bet unit").select_option("12")
    wait_text(a, "#preview-stack", "240")
    wait_text(a, "#preview-blinds", "6 / 12")
    a.get_by_label("Bet unit").select_option("10")
    a.get_by_role("button", name="Create room").press("Enter")
    a.get_by_role("heading", name="Waiting for opponent").wait_for()
    code = a.locator("#room-code").inner_text()
    assert code == "FRIEND42"
    if screenshots:
        a.screenshot(path=screenshots / "waiting.png")
    b.get_by_label("Room code").fill(code)
    b.get_by_role("button", name="Join room").click()
    for page in (a, b):
        wait_text(page, "#lifecycle", "Hand in play")
    wait_text(a, "#your-stack", f"{stacks[0]} chips")
    wait_text(b, "#your-stack", f"{stacks[1]} chips")
    assert a.locator("#opponent").inner_text() != b.locator("#opponent").inner_text()
    for page in (a, b):
        wait_text(page, "#pot", "15 chips")
        expect(
            page.locator("#opponent-cards").get_by_role("img", name="Face-down card")
        ).to_have_count(2)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if screenshots:
        a.screenshot(path=screenshots / "active.png")
    return a, b, host_context, guest_context, page_errors, traces


def play(a, b):
    for index, seat in enumerate(CHECK_PATH):
        button = (a if seat == "A" else b).get_by_role(
            "button", name="Call · 5" if index == 0 else "Check", exact=True
        )
        expect(button).to_be_enabled(timeout=4000)
        button.click()
        for page in (a, b):
            expect(page.locator("#board .face")).to_have_count(
                (0, 3, 3, 4, 4, 5, 5, 5)[index]
            )
            wait_text(page, "#pot", "0 chips" if index == 7 else "20 chips")


def showdown(a, b, screenshots):
    private_cards(a, ["9 of hearts", "5 of hearts"], ["Ten of spades", "3 of clubs"])
    private_cards(b, ["Ten of spades", "3 of clubs"], ["9 of hearts", "5 of hearts"])
    play(a, b)
    for page in (a, b):
        wait_text(page, "#result-title", "Player A wins at showdown")
        wait_text(page, "#pot", "0 chips")
    wait_text(a, "#your-stack", "210 chips")
    wait_text(b, "#your-stack", "190 chips")
    expect(
        a.locator("#opponent-cards").get_by_role(
            "img", name="Ten of spades", exact=True
        )
    ).to_be_visible()
    expect(
        b.locator("#opponent-cards").get_by_role("img", name="9 of hearts", exact=True)
    ).to_be_visible()
    if screenshots:
        a.screenshot(path=screenshots / "showdown.png")
    a.get_by_role("button", name="Ready", exact=True).click()
    wait_text(a, "#action-status", "Waiting for the other player to Ready.")
    b.get_by_role("button", name="Ready", exact=True).click()
    for page in (a, b):
        wait_text(page, "#game-title", "Hand 2 · Preflop")
        expect(
            page.locator("#opponent-cards").get_by_role("img", name="Face-down card")
        ).to_have_count(2)
    expect(b.get_by_role("button", name="Call · 5")).to_be_enabled()
    expect(a.locator("#opponent-markers")).to_contain_text("Dealer")
    expect(b.locator("#your-markers")).to_contain_text("Dealer")
    expect(b.locator("#turn-progress")).to_be_visible()
    expect(b.locator("#your-cards .face")).to_have_count(2)
    b.get_by_role("button", name="Fold", exact=True).click()
    wait_text(a, "#result-title", "Player A wins by fold")


def recovery(a, b, base, screenshots):
    repeated = []
    a.on("request", lambda request: repeated.append(request.method))
    a.reload()
    wait_text(a, "#lifecycle", "Hand in play")
    assert "POST" not in repeated, "refresh attempted room admission"
    private_cards(a, ["9 of hearts", "5 of hearts"])
    b.goto("about:blank")
    wait_text(a, "#lifecycle", "Hand paused")
    paused = a.locator("#turn-clock").inner_text()
    assert "paused" in paused
    expect(a.locator("#grace-b")).to_contain_text("Player B can return")
    expect(a.get_by_role("button", name="Call", exact=True)).to_be_disabled()
    if screenshots:
        a.screenshot(path=screenshots / "paused.png")
    b.goto(base)
    wait_text(a, "#lifecycle", "Hand in play")
    wait_text(b, "#lifecycle", "Hand in play")
    private_cards(b, ["Ten of spades", "3 of clubs"])
    expect(a.get_by_role("button", name="Call · 5")).to_be_enabled()
    a.get_by_role("button", name="Call · 5").click()
    wait_text(b, "#pot", "20 chips")


def fold_and_replacement(a, b):
    with a.expect_popup() as popup:
        a.evaluate("window.open(location.href)")
    replacement = popup.value
    wait_text(a, "#connection-label", "Session replaced")
    expect(a.get_by_role("button", name="Fold", exact=True)).to_be_disabled()
    expect(a.get_by_role("button", name="Reconnect", exact=True)).to_be_visible()
    expect(replacement.get_by_role("button", name="Fold", exact=True)).to_be_enabled()
    replacement.get_by_role("button", name="Fold", exact=True).click()
    wait_text(b, "#result-title", "Player B wins by fold")
    wait_text(b, "#your-stack", "205 chips")
    private_cards(b, ["Ten of spades", "3 of clubs"], ["9 of hearts", "5 of hearts"])
    wait_text(a, "#connection-label", "Session replaced")


def expire(a, b, base, screenshots, both):
    b.goto("about:blank")
    if both:
        a.goto("about:blank")
        sleep(0.9)
        a.goto(base)
        expected = "Match closed without a winner"
    else:
        expected = "Player A wins the match by forfeit"
    wait_text(a, "#result-title", expected)
    expect(a.locator("#result-detail")).to_contain_text("pot remains unawarded")
    wait_text(a, "#pot", "15 chips")
    expect(a.locator("#presence")).to_be_hidden()
    expect(a.locator("#turn-clock")).to_be_hidden()
    private_cards(a, ["9 of hearts", "5 of hearts"], ["Ten of spades", "3 of clubs"])
    expect(a.get_by_role("button", name="Fold", exact=True)).to_be_hidden()
    b.goto(base)
    wait_text(b, "#result-title", expected)
    expect(b.get_by_role("button", name="Fold", exact=True)).to_be_hidden()
    if screenshots and not both:
        a.screenshot(path=screenshots / "terminal.png")


def lost_ack_router(trace):
    dropped = False

    def configure(page):
        def handler(client):
            nonlocal dropped
            upstream = client.connect_to_server()

            def send(payload):
                frame = json.loads(payload)
                if frame["type"] == "action":
                    trace.append(payload)
                upstream.send(payload)

            def receive(payload):
                nonlocal dropped
                if json.loads(payload)["type"] == "action_ack" and not dropped:
                    dropped = True
                    client.close(code=1011, reason="fixture drops acknowledgment")
                else:
                    client.send(payload)

            client.on_message(send)
            upstream.on_message(receive)

        page.route_web_socket("**/ws", handler)

    return configure


def stale_router(trace):
    def configure(page):
        def handler(client):
            upstream = client.connect_to_server()

            def send(payload):
                frame = json.loads(payload)
                if frame["type"] == "action":
                    trace.append(frame["action_id"])
                    if len(trace) == 1:
                        frame["expected_revision"] = 0
                        payload = json.dumps(frame)
                    elif len(trace) == 2:
                        frame["action"] = "check"
                        payload = json.dumps(frame)
                upstream.send(payload)

            client.on_message(send)

        page.route_web_socket("**/ws", handler)

    return configure


def run_scenario(browser, name, screenshots):
    factories = {
        "tie": "tie",
        "timeout": "timeout",
        "forfeit": "expiry",
        "both-absent": "expiry",
        "engine-terminal": "short_stack",
    }
    trace = []
    configure = {"replay": lost_ack_router, "stale": stale_router}.get(
        name, lambda _: None
    )(trace)
    with server(factories.get(name, "showdown")) as base:
        if name == "errors":
            check_errors(browser, base)
            return
        a, b, ac, bc, page_errors, traces = table(
            browser,
            base,
            configure=configure,
            narrow=name == "showdown",
            screenshots=screenshots if name == "showdown" else None,
            stacks=(10, 375) if name == "engine-terminal" else (195, 190),
        )
        try:
            if name == "showdown":
                showdown(a, b, screenshots)
            elif name == "tie":
                play(a, b)
                wait_text(a, "#result-title", "Showdown tie")
                for page in (a, b):
                    wait_text(page, "#your-stack", "200 chips")
            elif name == "betting":
                a.get_by_role("button", name="Call · 5").click()
                b.get_by_role("button", name="Check", exact=True).click()
                b.get_by_role("button", name="Bet · 10").click()
                wait_text(a, "#pot", "30 chips")
                a.get_by_role("button", name="Raise · 20").click()
                wait_text(b, "#pot", "50 chips")
                b.get_by_role("button", name="Call · 10").click()
                wait_text(a, "#game-title", "Hand 1 · Turn")
                wait_text(a, "#your-stack", "170 chips")
                wait_text(b, "#your-stack", "170 chips")
                wait_text(a, "#pot", "60 chips")
            elif name == "engine-terminal":
                a.get_by_role("button", name="Fold", exact=True).click()
                for page in (a, b):
                    wait_text(page, "#result-title", "Player B wins the match")
                    expect(page.locator("#result-detail")).to_contain_text(
                        "Player B won the last hand."
                    )
                    expect(page.locator("#presence")).to_be_hidden()
                    expect(
                        page.get_by_role("button", name="Ready", exact=True)
                    ).to_be_hidden()
                wait_text(b, "#your-stack", "390 chips")
            elif name == "replacement":
                fold_and_replacement(a, b)
            elif name == "recovery":
                recovery(a, b, base, screenshots)
            elif name == "timeout":
                wait_text(a, "#result-title", "Player B wins by fold")
                expect(a.locator("#automatic")).to_contain_text("server applied fold")
                wait_text(b, "#your-stack", "205 chips")
            elif name in {"forfeit", "both-absent"}:
                expire(a, b, base, screenshots, both=name == "both-absent")
            elif name == "replay":
                a.get_by_role("button", name="Call · 5").click()
                wait_text(b, "#pot", "20 chips")
                expect(
                    a.get_by_text("Actions are unavailable.", exact=True)
                ).to_be_visible(timeout=4000)
                assert len(trace) == 2 and trace[0] == trace[1], (
                    f"expected two exact sends, saw {len(trace)}, equal={len(trace) >= 2 and trace[0] == trace[1]}"
                )
                wait_text(a, "#your-stack", "190 chips")
            elif name == "stale":
                for message in (
                    "The table changed.",
                    "The server rejected that action.",
                ):
                    a.get_by_role("button", name="Call · 5").click()
                    expect(a.locator("#notice")).to_contain_text(message)
                    wait_text(b, "#pot", "15 chips")
                a.get_by_role("button", name="Call · 5").click()
                wait_text(b, "#pot", "20 chips")
                assert len(set(trace)) == 3
            if name not in {"replay", "stale"}:
                verify_wire(traces, name)
            assert not page_errors, page_errors
        finally:
            ac.close()
            bc.close()


def check_errors(browser, base):
    separate = browser.new_context()
    try:
        page = separate.new_page()
        page.goto(base)
        page.get_by_label("Room code").fill("wrong-code")
        page.get_by_role("button", name="Join room").click()
        expect(page.locator("#notice")).to_contain_text("Room code not found")
        with page.expect_request("**/api/rooms"):
            page.route("**/api/rooms", lambda route: route.abort())
            page.get_by_role("button", name="Create room").click()
        expect(page.locator("#notice")).to_contain_text("did not confirm admission")
        page.unroute("**/api/rooms")

        def invalid_auth(client):
            upstream = client.connect_to_server()

            def send(payload):
                frame = json.loads(payload)
                if frame["type"] == "auth":
                    frame["token"] = "fixture-invalid"
                upstream.send(json.dumps(frame))

            client.on_message(send)

        page.route_web_socket("**/ws", invalid_auth)
        page.reload()
        page.get_by_role("button", name="Retry admission").click()
        wait_text(page, "#connection-label", "Session expired")
        expect(page.get_by_role("button", name="Reconnect", exact=True)).to_be_hidden()
        page.get_by_role("button", name="Leave table", exact=True).click()
        page.get_by_role("dialog").get_by_role(
            "button", name="Leave table", exact=True
        ).click()
        expect(page.get_by_role("heading", name="Create a room")).to_be_visible()
        page.get_by_role("button", name="Create room").click()
        expect(page.locator("#notice")).to_contain_text("An active room already exists")

        joiner = browser.new_context()
        other = joiner.new_page()
        other.goto(base)
        other.get_by_label("Room code").fill("FRIEND42")
        other.get_by_role("button", name="Join room").click()
        wait_text(other, "#game-title", "Hand 1 · Preflop")
        page.get_by_label("Room code").fill("FRIEND42")
        page.get_by_role("button", name="Join room").click()
        expect(page.locator("#notice")).to_contain_text("already has two players")
        joiner.close()
    finally:
        separate.close()


def main():
    choices = (
        "showdown",
        "tie",
        "betting",
        "engine-terminal",
        "replacement",
        "recovery",
        "timeout",
        "forfeit",
        "both-absent",
        "replay",
        "stale",
        "errors",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=choices, nargs="+", default=choices)
    parser.add_argument(
        "--browser", choices=("chromium", "firefox", "webkit"), default="chromium"
    )
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = getattr(playwright, args.browser).launch()
        print(f"{args.browser} {browser.version}", flush=True)
        for name in args.scenario:
            run_scenario(browser, name, args.screenshots)
            print(f"PASS {name}", flush=True)
        browser.close()


if __name__ == "__main__":
    main()
