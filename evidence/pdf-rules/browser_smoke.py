"""Two isolated browsers play the PDF-rule fixture through paid showdown."""

import json
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "browser-interface"))
from browser_smoke import observe_wire, server, wait_text  # noqa: E402


def play(browser):
    with server("pdf") as base:
        with browser.new_context() as ac, browser.new_context() as bc:
            a, b = ac.new_page(), bc.new_page()
            traffic = {"A": observe_wire(a), "B": observe_wire(b)}
            a.goto(base)
            b.goto(base)
            wait_text(a, "#preview-stack", "500")
            expect(a.locator("#bet-unit")).to_be_disabled()
            a.get_by_role("button", name="Create room").click()
            a.get_by_role("heading", name="Waiting for opponent").wait_for()
            b.get_by_label("Room code").fill(a.locator("#room-code").inner_text())
            b.get_by_role("button", name="Join room").click()
            for page, stack in ((a, 495), (b, 490)):
                wait_text(page, "#lifecycle", "Hand in play")
                wait_text(page, "#your-stack", f"{stack} chips")
                wait_text(page, "#pot", "15 chips")

            steps = (
                (a, "Call · 5", 20, 0),
                (b, "Check", 20, 3),
                (b, "Bet · 10", 30, 3),
                (a, "Call · 10", 40, 4),
                (b, "Bet · 20", 60, 4),
                (a, "Call · 20", 80, 5),
                (b, "Check", 80, 5),
                (a, "Check", 0, 5),
            )
            for page, label, pot, board_size in steps:
                button = page.get_by_role("button", name=label, exact=True)
                expect(button).to_be_enabled()
                button.click()
                for observer in (a, b):
                    wait_text(observer, "#pot", f"{pot} chips")
                    expect(observer.locator("#board .face")).to_have_count(board_size)

            for page in (a, b):
                wait_text(page, "#result-title", "Player A wins at showdown")
            wait_text(a, "#your-stack", "540 chips")
            wait_text(b, "#your-stack", "460 chips")

            for seat, (incoming, _, urls, logs) in traffic.items():
                assert urls and all(url.endswith("/ws") for url in urls)
                assert not logs, logs
                frames = [
                    frame
                    for frame in incoming
                    if frame.get("type") == "snapshot" and frame.get("hand_id") == 1
                ]
                assert frames
                assert {len(frame["board"]) for frame in frames} >= {0, 3, 4, 5}
                for frame in frames:
                    assert "deck" not in frame and "burn_cards" not in frame
                    assert sum(frame["stacks"].values()) + frame["pot"] == 1000
                    if frame["phase"] != "showdown":
                        hidden = ("Ts", "3c") if seat == "A" else ("9h", "5h")
                        encoded = json.dumps(frame)
                        assert all(json.dumps(card) not in encoded for card in hidden)

            a.get_by_role("button", name="Ready", exact=True).click()
            b.get_by_role("button", name="Ready", exact=True).click()
            for page in (a, b):
                wait_text(page, "#game-title", "Hand 2 · Preflop")
            print(
                "PDF rules: two browsers, 500-chip stacks, 5/10 blinds, 10/20 wagers, burned board, 540/460 showdown, private cards, rotated next hand"
            )


if __name__ == "__main__":
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            play(browser)
        finally:
            browser.close()
