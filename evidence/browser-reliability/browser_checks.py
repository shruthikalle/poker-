"""Reliability and usability checks using the existing two-player browser fixture."""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "browser-interface"))
from browser_smoke import (  # noqa: E402
    observe_wire,
    play,
    private_cards,
    server,
    table,
    verify_wire,
    wait_text,
)

VIEWPORTS = ((1440, 900), (1280, 720), (1024, 768), (768, 1024), (390, 844), (320, 568))


def network(browser):
    with server("showdown") as base:
        a, b, ac, bc, errors, traces = table(browser, base)
        try:
            ac.set_offline(True)
            wait_text(a, "#connection-label", "Offline")
            wait_text(a, "#presence", "Current opponent status is unknown.")
            expect(a.locator("#turn-clock")).to_be_hidden()
            expect(a.locator("#actions button:not([disabled])")).to_have_count(0)
            wait_text(b, "#lifecycle", "Hand paused")
            expect(b.locator("#grace-a")).to_contain_text("Player A can return")
            ac.set_offline(False)
            wait_text(a, "#lifecycle", "Hand in play")
            wait_text(b, "#lifecycle", "Hand in play")
            private_cards(a, ["9 of hearts", "5 of hearts"])
            a.get_by_role("button", name="Call · 5").click()
            wait_text(b, "#pot", "20 chips")
            assert not errors
            verify_wire(traces, "network")
            print(
                "offline: authority and timing hidden; peer paused; same seat resumed; pot 20",
                flush=True,
            )
        finally:
            ac.close()
            bc.close()


def restart(browser):
    ac = bc = None
    try:
        with server("showdown") as base:
            a, b, ac, bc, _, _ = table(browser, base)
            posts = []
            for page in (a, b):
                page.on("request", lambda request: posts.append(request.method))
            wait_text(a, "#lifecycle", "Hand in play")
        with server("showdown", urlsplit(base).port):
            for page in (a, b):
                wait_text(page, "#connection-label", "Session expired")
                expect(page.locator("#notice")).to_contain_text("no longer valid")
                expect(page.locator("#turn-clock")).to_be_hidden()
                page.get_by_role("button", name="Leave table", exact=True).click()
                page.get_by_role("dialog").get_by_role(
                    "button", name="Leave table"
                ).click()
                expect(page.get_by_role("button", name="Create room")).to_be_visible()
            assert "POST" not in posts
        print(
            "restart: both sessions invalidated; neither browser reserved a new seat",
            flush=True,
        )
    finally:
        if ac:
            ac.close()
        if bc:
            bc.close()


def command_delivery(browser, *, refresh=False):
    sent = []
    connections = 0
    suppressed = 0

    def configure(page):
        def handler(client):
            nonlocal connections
            connections += 1
            number = connections
            upstream = client.connect_to_server()

            def send(payload):
                if json.loads(payload)["type"] == "action":
                    sent.append(payload)
                upstream.send(payload)

            def receive(payload):
                nonlocal suppressed
                missing = "action_ack" if refresh else "snapshot"
                if number == 1 and sent and json.loads(payload)["type"] == missing:
                    suppressed += 1
                else:
                    client.send(payload)

            client.on_message(send)
            upstream.on_message(receive)

        page.route_web_socket("**/ws", handler)

    with server("showdown") as base:
        a, b, ac, bc, _, _ = table(browser, base, configure=configure)
        try:
            a.get_by_role("button", name="Call · 5").click()
            wait_text(b, "#pot", "20 chips")
            if refresh:
                wait_text(a, "#pot", "20 chips")
                wait_text(a, "#action-status", "Waiting for server confirmation…")
                assert suppressed == 1
                a.reload()
            expect(a.locator("#action-status")).to_have_text(
                "Actions are unavailable.", timeout=7000
            )
            wait_text(a, "#pot", "20 chips")
            wait_text(a, "#your-stack", "190 chips")
            assert connections == 2 and suppressed >= 1, (connections, suppressed)
            assert len(sent) == (2 if refresh else 1) and sent[0] == sent[-1]
            print(
                f"command {'refresh' if refresh else 'snapshot loss'}: {connections} sockets, "
                f"{len(sent)} exact command sends, pot 20",
                flush=True,
            )
        finally:
            ac.close()
            bc.close()


def initial_socket_failure(browser):
    attempts = 0
    with server("showdown") as base, browser.new_context() as context:
        page = context.new_page()

        def handler(client):
            nonlocal attempts
            attempts += 1
            client.connect_to_server()
            if attempts == 1:
                # Complete the real upgrade but drop the first auth frame.
                client.on_message(lambda _: client.close(code=1011))

        page.route_web_socket("**/ws", handler)
        posts = []
        page.on("request", lambda request: posts.append(request.method))
        page.goto(base)
        page.get_by_role("button", name="Create room").click()
        expect(page.get_by_role("heading", name="Waiting for opponent")).to_be_visible(
            timeout=7000
        )
        assert attempts == 2 and posts.count("POST") == 1
        print(
            "initial socket failure: reauthenticated on attempt 2 with a single admission",
            flush=True,
        )


def table_state(page):
    return page.locator(".chips, #pot").all_text_contents()


def chips(page):
    return sum(int(amount.split()[0]) for amount in table_state(page))


def extended(browser, peer):
    with server("showdown") as base:
        a, b, ac, bc, errors, traces = table(browser, base, peer_browser=peer)
        try:
            # Complete the deterministic first hand, then rotate four times.
            play(a, b)
            wait_text(a, "#result-title", "Player A wins at showdown")
            assert chips(a) == chips(b) == 400
            for hand in range(2, 6):
                for page in (a, b):
                    page.get_by_role("button", name="Ready", exact=True).click()
                for page in (a, b):
                    wait_text(page, "#game-title", f"Hand {hand} · Preflop")
                    wait_text(page, "#pot", "15 chips")
                    expect(page.locator("#opponent-cards .face")).to_have_count(0)
                    assert chips(page) == 400
                actor = b if hand % 2 == 0 else a
                observer = a if hand % 2 == 0 else b
                expect(actor.locator("#your-markers")).to_contain_text("Dealer")
                if hand in (2, 3):
                    # Repeated navigation uses the same storage and Uvicorn session.
                    actor.reload()
                    wait_text(actor, "#lifecycle", "Hand in play")
                actor.get_by_role("button", name="Fold", exact=True).click()
                wait_text(
                    observer,
                    "#result-title",
                    f"Player {'A' if hand % 2 == 0 else 'B'} wins by fold",
                )
                wait_text(actor, "#pot", "0 chips")
                assert chips(actor) == chips(observer) == 400
                assert sorted(table_state(actor)) == sorted(table_state(observer))
            verify_wire(traces, "extended")
            assert not errors
            print(
                "extended: five hands, four rotations, two refreshes, conserved total 400",
                flush=True,
            )
        finally:
            ac.close()
            bc.close()


def keyboard_activate(page, target, key="Enter"):
    expect(target).to_be_enabled()
    for _ in range(20):
        if target.evaluate("element => element === document.activeElement"):
            page.keyboard.press(key)
            return
        page.keyboard.press("Tab")
    raise AssertionError("target was not reachable with Tab")


def relative_luminance(rgb):
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    return sum(
        channel(value) * weight
        for value, weight in zip(rgb, (0.2126, 0.7152, 0.0722), strict=True)
    )


def contrast(foreground, background):
    ordered = sorted(
        relative_luminance(tuple(map(int, re.findall(r"\d+", color))))
        for color in (foreground, background)
    )
    return (ordered[1] + 0.05) / (ordered[0] + 0.05)


def usability(browser, screenshots):
    with (
        server("showdown") as base,
        browser.new_context(viewport={"width": 1440, "height": 900}) as ac,
        browser.new_context(
            viewport={"width": 390, "height": 844}, has_touch=True
        ) as bc,
    ):
        a, b = ac.new_page(), bc.new_page()
        _, guest_outgoing, _, _ = observe_wire(b)
        a.goto(base)
        b.goto(base)
        expect(a.get_by_role("main")).to_have_count(1)
        a.keyboard.press("Tab")
        expect(a.get_by_text("Table rules", exact=True)).to_be_focused()
        a.keyboard.press("Tab")
        expect(a.get_by_label("Bet unit")).to_be_focused()
        a.keyboard.press("Shift+Tab")
        expect(a.get_by_text("Table rules", exact=True)).to_be_focused()
        keyboard_activate(a, a.get_by_role("button", name="Create room"), "Space")
        expect(a.locator("#game-title")).to_be_focused()
        expect(a.get_by_role("heading", name="Waiting for opponent")).to_be_visible()
        keyboard_activate(a, a.get_by_role("button", name="Copy"))
        expect(a.locator("#notice")).to_contain_text(
            re.compile(r"Room code (copied|selected)")
        )

        join = b.get_by_label("Room code")
        join.tap()
        b.keyboard.type("FRIEND42")
        b.get_by_role("button", name="Join room").tap()
        wait_text(a, "#lifecycle", "Hand in play")
        wait_text(b, "#lifecycle", "Hand in play")
        expect(a.locator("#your-cards")).to_match_aria_snapshot("""
          - group "Your cards":
            - img "9 of hearts"
            - img "5 of hearts"
        """)
        assert "Undealt" not in a.locator("#board").aria_snapshot()
        assert "Your turn" in a.locator("#announcements").text_content()
        assert "9 of hearts" not in b.locator("#table-layout").inner_html()
        assert "Ten of spades" not in a.locator("#table-layout").inner_html()
        assert a.locator("#turn-clock").get_attribute("aria-live") is None
        colors = a.locator("#your-cards .card").first.evaluate(
            "(el) => { const style = getComputedStyle(el); return [style.color, style.backgroundColor]; }"
        )
        red_card = contrast(*colors)
        assert red_card >= 4.5
        focus = a.get_by_role("button", name="Call · 5")
        text_color, button_background, panel_background = focus.evaluate(
            "(el) => { const s = getComputedStyle(el); return [s.color, s.backgroundColor, getComputedStyle(el.closest('.panel')).backgroundColor]; }"
        )
        control_ratio = contrast(text_color, button_background)
        assert control_ratio >= 4.5
        for width, height in VIEWPORTS:
            a.set_viewport_size({"width": width, "height": height})
            assert a.evaluate("document.documentElement.scrollWidth <= innerWidth")
            for selector in (
                "#turn-clock",
                "#board",
                "#your-cards",
                "#pot",
                "#actions",
            ):
                expect(a.locator(selector)).to_be_visible()
            last_card = a.locator("#board .card").last.bounding_box()
            assert last_card["x"] + last_card["width"] <= width
        # Reflow with twice the base text size in a desktop-width window.
        a.set_viewport_size({"width": 768, "height": 900})
        a.evaluate("document.documentElement.style.fontSize = '200%'")
        assert a.evaluate("document.documentElement.scrollWidth <= innerWidth")
        expect(focus).to_be_visible()
        a.evaluate("document.documentElement.style.fontSize = ''")
        a.set_viewport_size({"width": 1440, "height": 900})
        if screenshots:
            a.screenshot(path=screenshots / "desktop-table.png")
        for _ in range(20):
            if focus.evaluate("element => element === document.activeElement"):
                break
            a.keyboard.press("Tab")
        expect(focus).to_be_focused()
        outline, style = focus.evaluate(
            "(el) => [getComputedStyle(el).outlineColor, getComputedStyle(el).outlineStyle]"
        )
        outline_ratio = contrast(outline, panel_background)
        assert style == "solid" and outline_ratio >= 3
        announced = a.locator("#announcements").text_content()
        displayed = a.locator("#turn-clock").text_content()
        a.wait_for_function(
            "previous => document.getElementById('turn-clock').textContent !== previous",
            arg=displayed,
        )
        expect(a.locator("#announcements")).to_have_text(announced)
        expect(focus).to_be_focused()
        a.keyboard.press("Enter")
        wait_text(b, "#pot", "20 chips")
        touch = b.get_by_role("button", name="Check", exact=True)
        expect(touch).to_be_enabled()
        box = touch.bounding_box()
        assert box["width"] >= 44 and box["height"] >= 44
        if screenshots:
            b.screenshot(path=screenshots / "touch-table.png", full_page=True)
        touch.scroll_into_view_if_needed()
        box = touch.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        b.touchscreen.tap(x, y)
        b.touchscreen.tap(x, y)
        wait_text(a, "#game-title", "Hand 1 · Flop")
        touch_actions = [
            frame["action"] for frame in guest_outgoing if frame["type"] == "action"
        ]
        print(f"touch double-tap: sent actions {touch_actions}", flush=True)
        assert touch_actions == ["check"]
        # Keyboard follows normal tab order and can settle/Ready without clicking.
        keyboard_activate(b, b.get_by_role("button", name="Check", exact=True))
        keyboard_activate(a, a.get_by_role("button", name="Check", exact=True))
        keyboard_activate(b, b.get_by_role("button", name="Check", exact=True))
        keyboard_activate(a, a.get_by_role("button", name="Check", exact=True))
        keyboard_activate(b, b.get_by_role("button", name="Check", exact=True))
        keyboard_activate(a, a.get_by_role("button", name="Check", exact=True))
        wait_text(a, "#result-title", "Player A wins at showdown")
        keyboard_activate(a, a.get_by_role("button", name="Ready", exact=True), "Space")
        keyboard_activate(b, b.get_by_role("button", name="Ready", exact=True))
        wait_text(a, "#game-title", "Hand 2 · Preflop")
        print(
            f"usability: 6 viewports, 200% root text, keyboard showdown and Ready, touch action {box['width']:.0f}×{box['height']:.0f}; "
            f"contrast red card {red_card:.2f}:1, action {control_ratio:.2f}:1, focus {outline_ratio:.2f}:1",
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choices = (
        "network",
        "restart",
        "initial-socket",
        "missing-snapshot",
        "pending-refresh",
        "extended",
        "usability",
    )
    parser.add_argument(
        "--scenario",
        nargs="+",
        choices=choices,
        default=choices,
    )
    parser.add_argument("--screenshots", type=Path)
    parser.add_argument(
        "--peer", choices=("chromium", "firefox", "webkit"), default="chromium"
    )
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        peer = (
            browser
            if args.peer == "chromium"
            else getattr(playwright, args.peer).launch()
        )
        print(f"chromium {browser.version}; {args.peer} {peer.version}", flush=True)
        for scenario in args.scenario:
            if scenario == "network":
                network(browser)
            elif scenario == "restart":
                restart(browser)
            elif scenario == "initial-socket":
                initial_socket_failure(browser)
            elif scenario in ("missing-snapshot", "pending-refresh"):
                command_delivery(browser, refresh=scenario == "pending-refresh")
            elif scenario == "extended":
                extended(browser, peer)
            else:
                usability(browser, args.screenshots)


if __name__ == "__main__":
    main()
