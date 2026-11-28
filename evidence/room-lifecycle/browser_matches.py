"""Play and release three PDF matches in one process with two browser profiles."""

import argparse
import sys
from contextlib import ExitStack
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "browser-interface"))
from browser_smoke import server, wait_text  # noqa: E402

STORAGE = "heads-up-session-v1"
DROP_CLOSE = """() => {
  const evidence = globalThis.releaseProbe = {dropNext: false, dropped: 0, sent: 0};
  class ProbeSocket extends WebSocket {
    send(payload) {
      if (JSON.parse(payload).type === "release_room") evidence.sent++;
      super.send(payload);
    }
    addEventListener(type, listener, options) {
      if (type !== "close") return super.addEventListener(type, listener, options);
      super.addEventListener(type, event => {
        if (event.code === 4001 && evidence.dropNext) {
          evidence.dropNext = false;
          evidence.dropped++;
        } else listener(event);
      }, options);
    }
  }
  globalThis.WebSocket = ProbeSocket;
}"""


def open_match(a, b):
    wait_text(a, "#preview-stack", "500")
    a.get_by_role("button", name="Create room", exact=True).click()
    a.get_by_role("heading", name="Waiting for opponent").wait_for()
    code = a.locator("#room-code").inner_text()
    b.get_by_label("Room code").fill(code)
    b.get_by_role("button", name="Join room", exact=True).click()
    secrets = []
    for page, stack in ((a, 495), (b, 490)):
        wait_text(page, "#lifecycle", "Hand in play")
        wait_text(page, "#game-title", "Hand 1 · Preflop")
        wait_text(page, "#your-stack", f"{stack} chips")
        wait_text(page, "#pot", "15 chips")
        expect(page.locator("#your-cards .face")).to_have_count(2)
        expect(page.locator("#opponent-cards .face")).to_have_count(0)
        expect(page.locator("#board .face")).to_have_count(0)
        stored = page.evaluate(
            "key => JSON.parse(sessionStorage.getItem(key))", STORAGE
        )
        secrets.append(stored["session"]["session_token"])
    return code, secrets


def forfeit(a, b):
    b.goto("about:blank")
    wait_text(a, "#result-title", "Player A wins the match by forfeit")
    expect(a.locator("#result-detail")).to_contain_text("pot remains unawarded")
    wait_text(a, "#your-stack", "495 chips")
    wait_text(a, "#pot", "15 chips")
    expect(a.locator("#opponent-cards .face")).to_have_count(0)
    expect(a.locator("#turn-clock")).to_be_hidden()
    expect(release(a)).to_be_disabled()


def acknowledge(page):
    return page.get_by_role("button", name="Acknowledge result", exact=True)


def release(page):
    return page.get_by_role("button", name="Release completed room", exact=True)


def assert_lobby(page):
    page.get_by_role("button", name="Create room", exact=True).wait_for(timeout=12_000)
    expect(page.locator("#title")).to_be_focused()
    expect(page.locator("#notice")).to_contain_text("room was released")
    expect(page.locator("#game")).to_be_hidden()
    expect(page.locator("#room-code")).to_have_text("")
    expect(page.locator("#result-title")).to_have_text("")
    expect(page.locator("#your-cards .face")).to_have_count(0)
    assert page.evaluate("key => sessionStorage.getItem(key) === null", STORAGE)


def replace_tab(page, base):
    saved = page.evaluate("key => sessionStorage.getItem(key)", STORAGE)
    replacement = page.context.new_page()
    replacement.goto(base)
    replacement.evaluate(
        "([key, saved]) => sessionStorage.setItem(key, saved)", [STORAGE, saved]
    )
    replacement.reload()
    wait_text(replacement, "#result-title", "Player A wins the match by forfeit")
    wait_text(page, "#connection-label", "Session replaced")
    expect(release(page)).to_be_disabled()
    return replacement


def run(first, second, *, retention):
    with (
        server("room_lifecycle") as base,
        first.new_context(viewport={"width": 390, "height": 844}) as ac,
        second.new_context() as bc,
    ):
        ac.add_init_script(f"({DROP_CLOSE})()")
        bc.add_init_script(f"({DROP_CLOSE})()")
        a, b = ac.new_page(), bc.new_page()
        for page in (a, b):
            page.goto(base)
        codes, credentials = set(), set()
        old_page = None
        for match in range(1, 4):
            code, tokens = open_match(a, b)
            assert (
                code not in codes
                and credentials.isdisjoint(tokens)
                and len(set(tokens)) == 2
            ), "credentials reused"
            codes.add(code)
            credentials.update(tokens)
            if old_page is not None:
                assert old_page.locator("#room-code").inner_text() != code
                expect(release(old_page)).to_be_disabled()
                old_page.reload()
                assert_lobby(old_page)
                old_page.close()
                old_page = None
            forfeit(a, b)
            expect(a.locator("#release-countdown")).to_contain_text("retention")
            assert a.evaluate("document.documentElement.scrollWidth <= innerWidth")
            b.goto(base)
            wait_text(b, "#result-title", "Player A wins the match by forfeit")
            expect(b.locator("#opponent-cards .face")).to_have_count(0)
            if match == 1:
                acknowledge(b).click()
                expect(a.locator("#release-status")).to_contain_text(
                    "Opponent acknowledged"
                )
                expect(release(a)).to_be_disabled()
                replacement = replace_tab(a, base)
                expect(acknowledge(a)).to_be_disabled()
                acknowledge(replacement).press("Enter")
                expect(release(replacement)).to_be_enabled()
                expect(replacement.locator("#result-title")).to_be_focused()
                expect(release(b)).to_be_enabled()
                release(replacement).press("Enter")
                old_page, a = a, replacement
            elif match == 2:
                acknowledge(a).click()
                acknowledge(b).click()
                expect(release(a)).to_be_enabled()
                a.evaluate(
                    "() => { releaseProbe.sent = 0; releaseProbe.dropNext = true; }"
                )
                b.evaluate("() => { releaseProbe.dropNext = true; }")
                release(a).click()
                b.wait_for_function("releaseProbe.dropped === 1")
                b.reload()
            else:
                acknowledge(a).click()
                expect(a.locator("#release-status")).to_contain_text("You acknowledged")
                expect(release(b)).to_be_disabled()
                if not retention:
                    acknowledge(b).click()
                expect(release(b)).to_be_enabled(timeout=65_000 if retention else 4000)
                release(b).press("Enter")
            assert_lobby(a)
            assert_lobby(b)
            print(
                f"PASS match {match}: fresh hand 1, 495/490 + pot 15, private terminal result, explicit release",
                flush=True,
            )
        assert len(codes) == 3 and len(credentials) == 6
        assert a.evaluate("releaseProbe") == {
            "dropNext": False,
            "dropped": 1,
            "sent": 1,
        }, "release was retransmitted or the fixture did not drop its close"
        print(
            "PASS replaced tab, lost retirement signal, refresh, lobby focus, and 390px terminal layout"
        )
        if retention:
            print(
                "PASS one-seat acknowledgment at the real 60-second boundary; the other seat released"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    engines = ("chromium", "firefox", "webkit")
    parser.add_argument("--browser", choices=engines, default="chromium")
    parser.add_argument("--peer", choices=engines)
    parser.add_argument("--retention", action="store_true")
    args = parser.parse_args()
    with sync_playwright() as playwright, ExitStack() as stack:
        first = stack.enter_context(getattr(playwright, args.browser).launch())
        second = (
            first
            if args.peer is None
            else stack.enter_context(getattr(playwright, args.peer).launch())
        )
        print(
            f"{args.browser} {first.version}; {args.peer or args.browser} {second.version}",
            flush=True,
        )
        run(first, second, retention=args.retention)
