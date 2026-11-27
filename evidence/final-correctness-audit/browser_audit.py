"""Rehearse real browsers, history traversal, and native zoom against local fixtures."""

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from playwright.sync_api import expect, sync_playwright

EVIDENCE = Path(__file__).resolve().parent.parent
sys.path[:0] = [
    str(EVIDENCE / name) for name in ("browser-interface", "browser-reliability")
]
from browser_checks import command_delivery, extended, restart  # noqa: E402
from browser_smoke import (  # noqa: E402
    fold_and_replacement,
    observe_wire,
    play,
    private_cards,
    server,
    table,
    verify_wire,
    wait_text,
)
from recovery_probe import admission, watchdog  # noqa: E402

HISTORY = """
window.auditHistory = [];
addEventListener("pageshow", event => {
  window.auditHistory.push({
    persisted: event.persisted,
    enabled: Array.from(document.querySelectorAll("#actions button:not([disabled])"))
      .filter(button => button.getClientRects().length > 0).length,
  });
});
"""


def go_away(page, base):
    page.goto(base + "/health", wait_until="domcontentloaded")


def come_back(page):
    page.go_back(wait_until="commit", timeout=8000)
    page.wait_for_function(
        "() => window.auditHistory?.length && location.pathname === '/'"
    )
    record = page.evaluate("window.auditHistory.at(-1)")
    if record["persisted"]:
        assert record["enabled"] == 0, record
        return "cache"
    reasons = page.evaluate("""() =>
      performance.getEntriesByType("navigation")[0]?.notRestoredReasons?.reasons
        ?.map(item => item.reason) ?? []""")
    return f"reload ({', '.join(reasons)})" if reasons else "reload"


def history(browser):
    records = {}
    with server("showdown") as base, browser.new_context() as context:
        page = context.new_page()
        page.add_init_script(HISTORY)
        page.goto(base)
        go_away(page, base)
        records["landing"] = come_back(page)
        expect(page.get_by_role("button", name="Create room")).to_be_visible()
    with server("showdown") as base:
        a, b, ac, bc, errors, traces = table(
            browser, base, configure=lambda page: page.add_init_script(HISTORY)
        )
        try:
            posts = []
            a.on("request", lambda request: posts.append(request.method))
            for step in ("active", "paused"):
                if step == "paused":
                    go_away(b, base)
                    wait_text(a, "#lifecycle", "Hand paused")
                go_away(a, base)
                if step == "active":
                    wait_text(b, "#lifecycle", "Hand paused")
                records[step] = come_back(a)
                if step == "paused":
                    b.go_back(wait_until="commit")
                for page in (a, b):
                    wait_text(page, "#lifecycle", "Hand in play")
                wait_text(a, "#pot", "15 chips")
                private_cards(
                    a, ["9 of hearts", "5 of hearts"], ["Ten of spades", "3 of clubs"]
                )
            a.get_by_role("button", name="Call · 5").click()
            wait_text(b, "#pot", "20 chips")
            assert "POST" not in posts and not errors
            verify_wire(traces, "history")
        finally:
            ac.close()
            bc.close()
    with server("expiry") as base:
        a, b, ac, bc, _, _ = table(
            browser, base, configure=lambda page: page.add_init_script(HISTORY)
        )
        try:
            go_away(a, base)
            wait_text(b, "#result-title", "Player B wins the match by forfeit")
            records["expired"] = come_back(a)
            wait_text(a, "#result-title", "Player B wins the match by forfeit")
            wait_text(a, "#pot", "15 chips")
            expect(a.locator("#turn-clock")).to_be_hidden()
            expect(a.locator("#actions button:visible")).to_have_count(0)
            go_away(a, base)
            records["terminal"] = come_back(a)
            wait_text(a, "#result-title", "Player B wins the match by forfeit")
        finally:
            ac.close()
            bc.close()
    with server("showdown") as base, browser.new_context() as ac:
        a = ac.new_page()
        a.add_init_script(HISTORY)
        a.goto(base)
        a.get_by_role("button", name="Create room").click()
        waiting = a.get_by_role("heading", name="Waiting for opponent")
        expect(waiting).to_be_visible()
        go_away(a, base)
        records["waiting"] = come_back(a)
        expect(waiting).to_be_visible()
    print(
        "history: " + ", ".join(f"{name}={mode}" for name, mode in records.items()),
        flush=True,
    )


def history_offline(browser):
    with server("showdown") as base:
        a, b, ac, bc, _, _ = table(
            browser, base, configure=lambda page: page.add_init_script(HISTORY)
        )
        try:
            ac.set_offline(True)
            wait_text(a, "#connection-label", "Offline")
            a.goto("about:blank", wait_until="commit")
            wait_text(b, "#lifecycle", "Hand paused")
            ac.set_offline(False)
            restored = come_back(a)
            print(
                f"offline history: {restored}, navigator.onLine={a.evaluate('navigator.onLine')}, "
                f"initial status={a.locator('#connection-label').inner_text()}",
                flush=True,
            )
            wait_text(a, "#lifecycle", "Hand in play")
            expect(a.get_by_role("button", name="Call · 5")).to_be_enabled()
            wait_text(a, "#pot", "15 chips")
        finally:
            ac.close()
            bc.close()


def pending_history(browser):
    commands = []
    dropped = False

    def configure(page):
        page.add_init_script(HISTORY)

        def route(client):
            upstream = client.connect_to_server()

            def outgoing(payload):
                if json.loads(payload)["type"] == "action":
                    commands.append(payload)
                upstream.send(payload)

            def incoming(payload):
                nonlocal dropped
                if json.loads(payload)["type"] == "action_ack" and not dropped:
                    dropped = True
                    return
                client.send(payload)

            client.on_message(outgoing)
            upstream.on_message(incoming)

        page.route_web_socket("**/ws", route)

    with server("showdown") as base:
        a, b, ac, bc, _, _ = table(browser, base, configure=configure)
        try:
            a.get_by_role("button", name="Call · 5").click()
            for page in (a, b):
                wait_text(page, "#pot", "20 chips")
            wait_text(a, "#action-status", "Waiting for server confirmation…")
            assert dropped
            go_away(a, base)
            wait_text(b, "#lifecycle", "Hand paused")
            mode = come_back(a)
            wait_text(a, "#action-status", "Actions are unavailable.")
            wait_text(b, "#lifecycle", "Hand in play")
            assert len(commands) == 2 and commands[0] == commands[1]
            wait_text(a, "#your-stack", "190 chips")
            wait_text(b, "#pot", "20 chips")
            print(
                f"pending history: {mode}, exact replay sent twice, one mutation and pot 20",
                flush=True,
            )
        finally:
            ac.close()
            bc.close()


def assistive_forms(browser):
    with server("showdown") as base, browser.new_context() as context:
        page = context.new_page()
        page.goto(base)
        field = page.get_by_label("Room code")
        field.fill("UNKNOWN")
        field.press("Enter")
        error = page.get_by_role("alert")
        expect(error).to_contain_text("Room code not found")
        expect(field).to_be_focused()
        print(
            "room-code feedback: focused field, "
            f"aria-invalid={field.get_attribute('aria-invalid')}, "
            f"aria-errormessage={field.get_attribute('aria-errormessage')}",
            flush=True,
        )
        expect(field).to_have_attribute("aria-invalid", "true")
        expect(field).to_have_attribute("aria-errormessage", "notice")
        field.fill("OTHER")
        expect(field).not_to_have_attribute("aria-invalid", "true")
        expect(error).not_to_contain_text("Room code not found")


def native_zoom(playwright):
    with TemporaryDirectory() as tmp, server("showdown") as base:
        directory = Path(tmp)
        extension = directory / "extension"
        extension.mkdir()
        (extension / "manifest.json").write_text(
            json.dumps(
                {
                    "manifest_version": 3,
                    "name": "Local test tab zoom",
                    "version": "1.0",
                    "host_permissions": ["http://127.0.0.1/*"],
                    "background": {"service_worker": "worker.js"},
                }
            )
        )
        (extension / "worker.js").write_text(
            "chrome.runtime.onInstalled.addListener(() => {});\n"
        )
        context = playwright.chromium.launch_persistent_context(
            str(directory / "profile"),
            channel="chromium",
            no_viewport=True,
            args=[
                f"--disable-extensions-except={extension}",
                f"--load-extension={extension}",
                "--window-size=1440,900",
            ],
        )
        try:
            worker = (
                context.service_workers[0]
                if context.service_workers
                else context.wait_for_event("serviceworker", timeout=7000)
            )
            page = context.pages[0]
            page.goto(base)
            width = page.evaluate("innerWidth")
            peer = context.new_page()
            peer.goto(base)
            selector = "() => document.documentElement.scrollWidth <= innerWidth"
            for level in (1, 1.5, 2):
                actual = worker.evaluate(
                    """async ([url, factor]) => {
                  const [tab] = await chrome.tabs.query({url, active: true});
                  await chrome.tabs.setZoom(tab.id, factor);
                  return chrome.tabs.getZoom(tab.id);
                }""",
                    [base + "/", level],
                )
                assert abs(level - actual) < 0.015
                page.wait_for_function(
                    "expected => Math.abs(innerWidth - expected) <= 2",
                    arg=round(width / level),
                )
                assert page.evaluate(selector)
                expect(page.get_by_role("button", name="Create room")).to_be_visible()
                expect(page.get_by_label("Room code")).to_be_visible()
                print(
                    f"native Chromium tab zoom: {actual:.2f}×, CSS viewport {page.evaluate('innerWidth')}px",
                    flush=True,
                )
            page.get_by_role("button", name="Create room").press("Enter")
            expect(
                page.get_by_role("heading", name="Waiting for opponent")
            ).to_be_visible()
            peer.get_by_label("Room code").fill("FRIEND42")
            peer.get_by_role("button", name="Join room").click()
            wait_text(page, "#turn-status", "Your turn")
            private_cards(page, ["9 of hearts", "5 of hearts"])
            assert page.evaluate(selector)
            call = page.get_by_role("button", name="Call · 5")
            call.focus()
            expect(call).to_be_focused()
            call.press("Space")
            wait_text(peer, "#pot", "20 chips")
            print(
                "native zoom: reflow, private card labels, focus, and keyboard call passed at 200%",
                flush=True,
            )
        finally:
            context.close()


def installed_app(browser, url):
    with browser.new_context() as ac, browser.new_context() as bc:
        a, b = ac.new_page(), bc.new_page()
        for page in (a, b):
            page.goto(url)
        expected = [
            "index.html",
            "styles.css",
            "js/app.mjs",
            "js/network.mjs",
            "js/render.mjs",
            "js/session.mjs",
            "js/state.mjs",
        ]
        for path in expected:
            assert ac.request.get(f"{url}/assets/{path}").status == 200
        assert ac.request.get(f"{url}/health").json() == {"status": "ok"}
        a.get_by_role("button", name="Create room").click()
        expect(a.get_by_role("heading", name="Waiting for opponent")).to_be_visible()
        b.get_by_label("Room code").fill(a.locator("#room-code").inner_text())
        b.get_by_role("button", name="Join room").click()
        wait_text(a, "#your-stack", "195 chips")
        wait_text(b, "#your-stack", "190 chips")
        a.get_by_role("button", name="Fold", exact=True).press("Enter")
        wait_text(b, "#result-title", "Player B wins by fold")
        wait_text(a, "#your-stack", "195 chips")
        wait_text(b, "#your-stack", "205 chips")
        for page in (a, b):
            page.get_by_role("button", name="Ready", exact=True).click()
            expect(page.locator("#opponent-cards .face")).to_have_count(0)
        wait_text(a, "#game-title", "Hand 2 · Preflop")
        wait_text(b, "#your-stack", "200 chips")
        wait_text(a, "#your-stack", "185 chips")
        wait_text(b, "#pot", "15 chips")
        print(
            "installed app: 7 assets, health, independent admission and sockets, fold 195/205, Ready → 185/200 + pot 15",
            flush=True,
        )


def input_edges(browser):
    with (
        server("showdown") as base,
        browser.new_context() as ac,
        browser.new_context(
            has_touch=True, viewport={"width": 390, "height": 844}
        ) as bc,
    ):
        a, b = ac.new_page(), bc.new_page()
        _, outgoing, _, _ = observe_wire(b)
        for page in (a, b):
            page.goto(base)
        a.get_by_role("button", name="Create room").click()
        expect(a.get_by_role("heading", name="Waiting for opponent")).to_be_visible()
        b.get_by_label("Room code").fill(a.locator("#room-code").inner_text())
        b.get_by_role("button", name="Join room").click()
        call = a.get_by_role("button", name="Call · 5")
        expect(call).to_be_enabled()
        call.press("Enter")
        check = b.get_by_role("button", name="Check", exact=True)
        expect(check).to_be_enabled()
        check.focus()
        b.keyboard.down("Enter")
        wait_text(a, "#game-title", "Hand 1 · Flop")
        b.keyboard.down("Enter")
        b.keyboard.up("Enter")
        expect(b.locator("#action-status")).to_be_focused()
        assert [frame["action"] for frame in outgoing if frame["type"] == "action"] == [
            "check"
        ]
        check.tap()
        wait_text(a, "#turn-status", "Your turn")
        a.get_by_role("button", name="Check", exact=True).press("Enter")
        wait_text(b, "#game-title", "Hand 1 · Turn")
        bet = b.get_by_role("button", name="Bet · 10")
        bet.tap()
        wait_text(a, "#pot", "30 chips")
        assert [frame["action"] for frame in outgoing if frame["type"] == "action"] == [
            "check",
            "check",
            "bet",
        ]
        print(
            "input edges: held Enter submitted one check, focus moved to action status, deliberate touch Check and Bet both worked",
            flush=True,
        )


def suspension(browser):
    with server("showdown") as base:
        a, b, ac, bc, _, traces = table(browser, base)
        try:
            display = a.locator("#turn-clock")
            before = int(display.inner_text().split("s")[0])
            cdp = ac.new_cdp_session(a)
            cdp.send("Page.setWebLifecycleState", {"state": "frozen"})
            # The peer confirms the shared server countdown advances while A is frozen.
            b.wait_for_function(
                "limit => Number.parseInt(document.querySelector('#turn-clock').textContent) <= limit",
                arg=before - 2,
            )
            cdp.send("Page.setWebLifecycleState", {"state": "active"})
            a.wait_for_function(
                "limit => Number.parseInt(document.querySelector('#turn-clock').textContent) <= limit",
                arg=before - 2,
            )
            after = int(display.inner_text().split("s")[0])
            wait_text(a, "#pot", "15 chips")
            wait_text(b, "#pot", "15 chips")
            assert not any(frame["type"] == "action" for frame in traces["A"][1])
            a.get_by_role("button", name="Call · 5").click()
            wait_text(b, "#pot", "20 chips")
            print(
                f"CDP freeze: countdown recovered {before}s → {after}s, no synthetic poker command, call applied once",
                flush=True,
            )
        finally:
            ac.close()
            bc.close()


def rehearsal(browser):
    started = monotonic()
    with server("showdown") as base:
        a, b, ac, bc, _, traces = table(browser, base)
        try:
            play(a, b)
            for page, own in ((a, 210), (b, 190)):
                wait_text(page, "#result-title", "Player A wins at showdown")
                wait_text(page, "#your-stack", f"{own} chips")
                wait_text(page, "#pot", "0 chips")
            a.get_by_role("button", name="Ready", exact=True).click()
            expect(a.locator("#turn-clock")).to_be_hidden()
            b.get_by_role("button", name="Ready", exact=True).click()
            wait_text(b, "#game-title", "Hand 2 · Preflop")
            go_away(a, base)
            wait_text(b, "#lifecycle", "Hand paused")
            saved = b.locator("#turn-clock").inner_text()
            assert "paused" in saved
            a.go_back(wait_until="commit")
            wait_text(b, "#lifecycle", "Hand in play")
            verify_wire(traces, "showdown")
        finally:
            ac.close()
            bc.close()
    with server("expiry") as base:
        a, b, ac, bc, _, _ = table(browser, base)
        try:
            go_away(b, base)
            wait_text(a, "#result-title", "Player A wins the match by forfeit")
            wait_text(a, "#your-stack", "195 chips")
            wait_text(a, "#opponent-stack", "190 chips")
            wait_text(a, "#pot", "15 chips")
        finally:
            ac.close()
            bc.close()
    print(
        f"rehearsal: private admission → 210/190 showdown → Ready → pause ({saved}) → resume; fresh fixture forfeit 195+190+15=400; {monotonic() - started:.2f}s",
        flush=True,
    )


def offline_audit(browser):
    with server("showdown") as base:
        a, b, ac, bc, _, _ = table(browser, base)
        try:
            a.evaluate("""() => {
                window.offlineEvents = 0;
                addEventListener("offline", () => window.offlineEvents++);
            }""")
            ac.set_offline(True)
            connectivity = a.evaluate("""async () => {
              let fetchOk = false;
              try {
                fetchOk = (await fetch("/health", {
                  cache: "no-store", signal: AbortSignal.timeout(1500)
                })).ok;
              } catch {}
              return {online: navigator.onLine, fetchOk, events: window.offlineEvents};
            }""")
            controlled = not connectivity["events"]
            if controlled:
                a.evaluate("dispatchEvent(new Event('offline'))")
            wait_text(a, "#connection-label", "Offline")
            wait_text(a, "#presence", "Current opponent status is unknown.")
            expect(a.locator("#actions button:not([disabled])")).to_have_count(0)
            expect(a.locator("#turn-clock")).to_be_hidden()
            wait_text(b, "#lifecycle", "Hand paused")
            ac.set_offline(False)
            if controlled:
                a.evaluate("dispatchEvent(new Event('online'))")
            for page in (a, b):
                wait_text(page, "#lifecycle", "Hand in play")
            private_cards(a, ["9 of hearts", "5 of hearts"])
            print(
                f"offline: navigator.onLine={connectivity['online']}, fetch succeeded={connectivity['fetchOk']}, "
                f"browser events={connectivity['events']}, "
                f"synthetic event={controlled}; actions suspended, peer paused, seat restored",
                flush=True,
            )
        finally:
            ac.close()
            bc.close()


def reliability(browser):
    for kind in ("create", "join"):
        admission(browser, kind, True, refresh=True)
    watchdog(browser, True)
    command_delivery(browser)
    offline_audit(browser)
    restart(browser)
    with server("showdown") as base:
        a, b, ac, bc, _, _ = table(browser, base)
        try:
            fold_and_replacement(a, b)
            print("replacement: displaced tab stopped; current seat folded", flush=True)
        finally:
            ac.close()
            bc.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--engine", choices=("chromium", "firefox", "webkit"), default="chromium"
    )
    parser.add_argument(
        "--case",
        choices=(
            "history",
            "history-offline",
            "pending-history",
            "forms",
            "zoom",
            "installed",
            "input",
            "suspension",
            "rehearsal",
            "reliability",
            "mixed",
        ),
        required=True,
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--peer", choices=("firefox", "webkit"), default="firefox")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        if args.case == "zoom":
            native_zoom(playwright)
            return
        options = (
            {
                "channel": "chromium",
                "ignore_default_args": ["--disable-back-forward-cache"],
            }
            if args.engine == "chromium"
            and args.case in ("history", "history-offline", "pending-history")
            else {}
        )
        browser = getattr(playwright, args.engine).launch(**options)
        print(f"{args.engine} {browser.version}", flush=True)
        try:
            if args.case == "mixed":
                peer = getattr(playwright, args.peer).launch()
                try:
                    print(f"{args.peer} {peer.version}", flush=True)
                    extended(browser, peer)
                finally:
                    peer.close()
            elif args.case == "installed":
                installed_app(browser, args.url.rstrip("/"))
            else:
                {
                    "history": history,
                    "history-offline": history_offline,
                    "pending-history": pending_history,
                    "forms": assistive_forms,
                    "input": input_edges,
                    "suspension": suspension,
                    "rehearsal": rehearsal,
                    "reliability": reliability,
                }[args.case](browser)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
