"""Inspect product states through two browser seats and capture real UI evidence."""

import argparse
import sys
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "browser-interface"))
from browser_smoke import (  # noqa: E402
    expire,
    private_cards,
    server,
    table,
    verify_wire,
    wait_text,
)

VIEWPORTS = ((1440, 900), (1280, 720), (1024, 768), (768, 1024), (390, 844), (320, 568))


def screenshot(page, directory, name):
    if directory:
        page.screenshot(path=directory / f"{name}.png", full_page=True)


def fit(page, selectors):
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    for selector in selectors:
        box = page.locator(selector).bounding_box()
        assert box is not None, selector
        assert box["x"] >= 0 and box["x"] + box["width"] <= page.evaluate(
            "innerWidth"
        ), selector


def waiting_and_new_room(browser, directory, before):
    with browser.new_context(viewport={"width": 1440, "height": 900}) as context:
        host = context.new_page()
        port = None
        with server("showdown") as base, browser.new_context() as peer:
            port = urlsplit(base).port
            host.goto(base)
            screenshot(host, directory, "landing")
            host.get_by_label("Bet unit").select_option("12")
            wait_text(host, "#preview-stack", "240")
            wait_text(host, "#preview-blinds", "6 / 12")
            host.get_by_label("Bet unit").select_option("10")
            host.get_by_role("button", name="Create room").press("Enter")
            expect(
                host.get_by_role("heading", name="Waiting for opponent")
            ).to_be_visible()
            host.get_by_role("button", name="Copy", exact=True).press("Space")
            wait_text(host, "#room-code", "FRIEND42")
            expect(host.locator("#notice")).to_contain_text("Room code")
            screenshot(host, directory, "waiting")
            host.evaluate("dispatchEvent(new Event('offline'))")
            wait_text(host, "#connection-label", "Offline")
            heading = host.locator("#waiting h2").inner_text()
            print(f"offline waiting heading: {heading}", flush=True)
            if not before:
                assert heading == "Offline"
            host.evaluate("dispatchEvent(new Event('online'))")
            expect(
                host.get_by_role("heading", name="Waiting for opponent")
            ).to_be_visible()
            guest = peer.new_page()
            guest.goto(base)
            guest.get_by_label("Room code").fill("FRIEND42")
            guest.get_by_role("button", name="Join room").click()
            wait_text(host, "#game-title", "Hand 1 · Preflop")
            host.get_by_role("button", name="Fold", exact=True).click()
            wait_text(guest, "#result-title", "Player B wins by fold")
            screenshot(guest, directory, "fold")
            host.locator("#leave").click()
            host.get_by_role("dialog").get_by_role("button", name="Leave table").click()
            expect(host.locator("#your-cards [role=img]")).to_have_count(0)

        with server("showdown", port):
            host.get_by_role("button", name="Create room").press("Enter")
            expect(
                host.get_by_role("heading", name="Waiting for opponent")
            ).to_be_visible()
            title = host.locator("#game-title").inner_text()
            print(f"fresh table heading after leaving an old hand: {title}", flush=True)
            if not before:
                assert title == "Private table"


def active_journey(browser, directory, before):
    with server("showdown") as base:
        a, b, ac, bc, errors, traces = table(browser, base, narrow=True)
        try:
            screenshot(a, directory, "preflop")
            for width, height in VIEWPORTS:
                a.set_viewport_size({"width": width, "height": height})
                fit(a, ("#game-title", "#turn-clock", "#pot", "#board", "#actions"))
            screenshot(a, directory, "mobile")
            a.set_viewport_size({"width": 1440, "height": 900})
            a.evaluate("dispatchEvent(new Event('offline'))")
            wait_text(a, "#lifecycle", "Last known table")
            displayed = a.locator(".seat.acting").count()
            print(f"offline active-seat highlights: {displayed}", flush=True)
            if not before:
                assert displayed == 0
                assert "Acting" not in a.locator("#your-markers").inner_text()
            expect(a.locator("#turn-clock")).to_be_hidden()
            expect(a.locator("#actions button:enabled")).to_have_count(0)
            wait_text(b, "#lifecycle", "Hand paused")
            screenshot(b, directory, "paused")
            a.evaluate("dispatchEvent(new Event('online'))")
            wait_text(a, "#lifecycle", "Hand in play")
            recovered_notice = a.locator("#notice").inner_text()
            print(
                f"notice after automatic recovery: {recovered_notice or '(empty)'}",
                flush=True,
            )
            if not before:
                assert "unreachable" not in recovered_notice
            expect(a.locator("#you.acting")).to_be_visible()
            private_cards(
                a, ["9 of hearts", "5 of hearts"], ["Ten of spades", "3 of clubs"]
            )

            with a.expect_popup() as popup:
                # WebKit requires a trusted gesture to open a second window.
                a.evaluate("""() => {
                    const test = document.createElement('button');
                    test.id = 'duplicate-context';
                    test.textContent = 'Duplicate session';
                    test.onclick = () => { window.open(location.href); test.remove(); };
                    document.body.append(test);
                }""")
                a.locator("#duplicate-context").click()
            duplicate = popup.value
            wait_text(a, "#connection-label", "Session replaced")
            a.get_by_role("button", name="Reconnect", exact=True).press("Enter")
            wait_text(a, "#connection-label", "Connected")
            wait_text(duplicate, "#connection-label", "Session replaced")
            focus = a.evaluate(
                "document.activeElement.id || document.activeElement.localName"
            )
            print(f"keyboard focus after reclaiming replaced seat: {focus}", flush=True)
            if not before:
                assert focus == "game-title"
            duplicate.close()

            call = a.get_by_role("button", name="Call · 5")
            expect(call).to_be_enabled()
            call.click()
            b.get_by_role("button", name="Check", exact=True).click()
            wait_text(a, "#game-title", "Hand 1 · Flop")
            screenshot(a, directory, "flop")
            for seat, move in [(b, "Bet · 10"), (a, "Raise · 20"), (b, "Call · 10")]:
                seat.get_by_role("button", name=move, exact=True).click()
            wait_text(a, "#pot", "60 chips")
            for seat in (b, a, b, a):
                seat.get_by_role("button", name="Check", exact=True).click()
            wait_text(a, "#result-title", "Player A wins at showdown")
            screenshot(a, directory, "showdown")
            wait_text(a, "#your-stack", "230 chips")
            wait_text(b, "#your-stack", "170 chips")
            for seat in (a, b):
                seat.get_by_role("button", name="Ready", exact=True).click()
            wait_text(a, "#game-title", "Hand 2 · Preflop")
            expect(b.locator("#your-markers")).to_contain_text("Dealer")
            expect(a.locator("#opponent-cards .face")).to_have_count(0)
            verify_wire(traces, "quality")
            assert not errors, errors
        finally:
            ac.close()
            bc.close()
    with server("expiry") as base:
        a, b, ac, bc, _, _ = table(browser, base)
        try:
            expire(a, b, base, directory, both=False)
        finally:
            ac.close()
            bc.close()
    print(
        "six viewports; two seats; betting, raise, showdown, fold, Ready, reconnect, and forfeit verified",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--browser", choices=("chromium", "firefox", "webkit"), default="chromium"
    )
    parser.add_argument("--screenshots", type=Path)
    parser.add_argument("--observe-before", action="store_true")
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        with getattr(playwright, args.browser).launch() as browser:
            print(f"{args.browser} {browser.version}", flush=True)
            waiting_and_new_room(browser, args.screenshots, args.observe_before)
            active_journey(browser, args.screenshots, args.observe_before)


if __name__ == "__main__":
    main()
