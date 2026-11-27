"""Observe admission response loss and command recovery on a real local server."""

import argparse
import json
import sys
from pathlib import Path
from time import monotonic

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "browser-interface"))
from browser_smoke import server, table, wait_text  # noqa: E402


def admission(browser, kind, fixed, *, before=False, refresh=False):
    with server("showdown") as base, browser.new_context() as context:
        page = context.new_page()
        page.goto(base)
        if kind == "join":
            host = context.request.post(f"{base}/api/rooms", data={"bet_unit": 10})
            assert host.status == 201
        status = []
        bodies = []
        headers = []
        results = []

        def intercept(route):
            bodies.append(route.request.post_data)
            headers.append(route.request.headers.get("admission-key"))
            if before and not status:
                status.append(None)
                route.abort()
                return
            try:
                response = route.fetch()
            except Exception:
                # Playwright's error details can contain outgoing headers.
                raise AssertionError("fixture could not forward admission") from None
            status.append(response.status)
            results.append(response.json())
            if len(status) == 1:
                route.abort()
            else:
                route.fulfill(response=response)

        suffix = "/join" if kind == "join" else ""
        page.route(f"**/api/rooms{suffix}", intercept)
        button = page.get_by_role("button", name=f"{kind.title()} room")
        if kind == "join":
            page.get_by_label("Room code").fill("FRIEND42")
        button.click()
        expect(page.locator("#notice")).to_contain_text("did not confirm admission")
        if refresh:
            page.reload()
        if fixed:
            page.get_by_role("button", name="Retry admission").click()
            expect(page.locator("#game")).to_be_visible()
            assert status == (
                [None, 200 if kind == "join" else 201]
                if before
                else [200, 200]
                if kind == "join"
                else [201, 201]
            )
            assert bodies[0] == bodies[1] and headers[0] == headers[1] and headers[0]
            if not before:
                assert results[0] == results[1]
            assert results[-1]["seat"] == ("B" if kind == "join" else "A")
        else:
            button.click()
            expect(page.locator("#notice")).to_contain_text(
                "already has two players"
                if kind == "join"
                else "active room already exists"
            )
            assert status == [200 if kind == "join" else 201, 409]
        # Use the first successfully committed token only in memory. Check the seat
        # and table readiness without printing either request or credential.
        token = results[0]["session_token"]
        identity = context.request.get(
            f"{base}/api/session", headers={"Authorization": f"Bearer {token}"}
        )
        assert identity.status == 200
        assert identity.json() == {
            "seat": "B" if kind == "join" else "A",
            "table_ready": kind == "join",
        }
        print(
            f"{kind}: upstream statuses {status}, original seat {identity.json()['seat']}, "
            f"ready={identity.json()['table_ready']}, refresh={refresh}",
            flush=True,
        )


def watchdog(browser, fixed):
    actions = []
    requests = 0
    dropped = 0
    first_send = retry_at = 0

    def configure(page):
        def handler(client):
            upstream = client.connect_to_server()

            def send(payload):
                nonlocal first_send, retry_at, requests
                frame = json.loads(payload)
                if frame["type"] == "action":
                    actions.append(payload)
                    if len(actions) == 1:
                        first_send = monotonic()
                    elif len(actions) == 2:
                        retry_at = monotonic()
                elif frame["type"] == "snapshot_request":
                    requests += 1
                upstream.send(payload)

            def receive(payload):
                nonlocal dropped
                if json.loads(payload)["type"] == "action_ack" and not dropped:
                    dropped += 1
                else:
                    client.send(payload)

            client.on_message(send)
            upstream.on_message(receive)

        page.route_web_socket("**/ws", handler)
        page.add_init_script("""
            setInterval(() => document.dispatchEvent(new Event("visibilitychange")), 600);
        """)

    with server("showdown") as base:
        a, b, ac, bc, _, _ = table(browser, base, configure=configure)
        try:
            a.get_by_role("button", name="Call · 5").click()
            wait_text(b, "#pot", "20 chips")
            if fixed:
                expect(a.locator("#action-status")).to_have_text(
                    "Actions are unavailable.", timeout=7000
                )
                elapsed = retry_at - first_send
                assert (
                    4.3 < elapsed < 7 and len(actions) == 2 and actions[0] == actions[1]
                )
            else:
                # The test supplies real same-revision snapshots past the 4.5s threshold.
                a.wait_for_timeout(5800)
                elapsed = monotonic() - first_send
                assert len(actions) == 1
                expect(a.locator("#action-status")).to_have_text(
                    "Waiting for server confirmation…"
                )
            assert dropped == 1 and requests >= 5
            wait_text(a, "#pot", "20 chips")
            wait_text(a, "#your-stack", "190 chips")
            print(
                f"watchdog: {elapsed:.2f}s, {requests} snapshot requests, "
                f"{len(actions)} command sends, pot 20, stack A 190",
                flush=True,
            )
        finally:
            ac.close()
            bc.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--only", choices=("admission", "watchdog"))
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            if args.only != "watchdog":
                for kind in ("create", "join"):
                    admission(
                        browser, kind, not args.baseline, refresh=not args.baseline
                    )
                if not args.baseline:
                    admission(browser, "create", True, before=True, refresh=True)
            if args.only != "admission":
                watchdog(browser, not args.baseline)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
