"""Real Chromium / FastAPI smoke checks on a disposable, synthetic graph.

Run after `npm ci --prefix frontend && npm run build --prefix frontend` with
`pip install -e '.[dev,server]' playwright` and Playwright Chromium installed.
No model is invoked, no user project is touched, no production test hook is added.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import httpx
import uvicorn
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import expect, sync_playwright

from simulanka.layout import init_project
from simulanka.server.app import create_app

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "acceptance"


class StreamFault:
    """Test-only transport outage: end live streams and reject reconnects."""

    def __init__(self, app: Any, broken: threading.Event) -> None:
        self.app = app
        self.broken = broken

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("path") != "/events":
            await self.app(scope, receive, send)
            return
        if self.broken.is_set():
            await send({"type": "http.response.start", "status": 503, "headers": []})
            await send({"type": "http.response.body", "body": b"smoke-test outage"})
            return

        async def controlled_receive() -> Any:
            if self.broken.is_set():
                return {"type": "http.disconnect"}
            return await receive()

        await self.app(scope, controlled_receive, send)


def run() -> None:
    OUTPUT.mkdir(exist_ok=True)
    checks: list[str] = []
    page_errors: list[str] = []
    with TemporaryDirectory(prefix="simulanka-browser-") as project:
        layout = init_project(Path(project)).layout
        broken = threading.Event()
        app = create_app(layout)
        app.add_middleware(StreamFault, broken=broken)
        app.mount("/", StaticFiles(directory=ROOT / "frontend" / "dist", html=True))
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", timeout_graceful_shutdown=2))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        worker.start()
        deadline = time.monotonic() + 15
        while not server.started:
            if time.monotonic() > deadline or not worker.is_alive():
                raise RuntimeError("Disposable FastAPI server did not start")
            time.sleep(0.05)

        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=15) as api:
                def request(method: str, path: str, **kwargs: Any) -> Any:
                    response = api.request(method, path, **kwargs)
                    if response.is_error:
                        raise AssertionError(f"{method} {path}: {response.status_code} {response.text}")
                    return response.json()

                top = request("GET", "/graph")
                roots = sorted(top["nodes"], key=lambda n: n["name"] != "baselines")
                root_positions = {n["id"]: [70 + (i % 3) * 320, 110 + (i // 3) * 160] for i, n in enumerate(roots)}
                request("POST", "/ui/positions/top", json=root_positions)
                baselines = next(n["id"] for n in roots if n["name"] == "baselines")
                model = request("POST", "/node", json={"type": "model", "name": "Workspace demo", "parent": baselines})
                model_id = model["node_id"]
                request("POST", f"/ui/positions/{baselines}", json={model_id: [70, 110]})
                blocks = []
                for name in ["Input", "Encoder", "Decoder", "Output"]:
                    blocks.append(request("POST", "/node", json={
                        "type": "module", "name": name, "parent": model_id,
                        "ports": [{"name": "in", "direction": "in", "port_type": "tensor"},
                                  {"name": "out", "direction": "out", "port_type": "tensor"}],
                    }))
                request("POST", f"/ui/positions/{model_id}", json={b["node_id"]: [75 + i * 290, 170] for i, b in enumerate(blocks)})
                edges = []
                for left, right in zip(blocks, blocks[1:]):
                    edges.append(request("POST", "/edge", json={"src_port": left["port_ids"][1], "dst_port": right["port_ids"][0]}))
                # Real HTTP round-trips, including the server-authoritative connected-port guard.
                connected_port = blocks[0]["port_ids"][1]
                assert api.post(f"/port/{connected_port}/update", json={"direction": "in"}).status_code == 422
                assert api.delete(f"/port/{connected_port}").status_code == 422
                request("POST", f"/port/{connected_port}/update", json={"name": "features"})
                extra = request("POST", f"/node/{blocks[0]['node_id']}/ports", json={"name": "scratch", "direction": "out", "port_type": "tensor"})
                request("DELETE", f"/port/{extra['port_id']}")
                loaded = request("GET", f"/graph?root={model_id}")
                assert extra["port_id"] not in {p["id"] for p in loaded["ports"]}
                assert len(loaded["edges"]) == 3
                checks.append("real API: Port create/delete/rename, connected topology guard, reload consistency")

                with sync_playwright() as p:
                    browser = p.chromium.launch()
                    context = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
                    context.tracing.start(screenshots=True, snapshots=True, sources=True)
                    page = context.new_page()
                    page.on("pageerror", lambda error: page_errors.append(str(error)))
                    try:
                        page.goto(str(api.base_url), wait_until="domcontentloaded")
                        expect(page.locator(".connection")).to_have_text("Live", timeout=15000)
                        expect(page.locator(".primary-status")).to_have_text("Ready", timeout=15000)
                        expect(page.get_by_role("button", name="Back", exact=True)).to_be_disabled()
                        expect(page.get_by_role("navigation", name="Graph location")).to_be_visible()
                        page.screenshot(path=str(OUTPUT / "workspace-desktop.png"))
                        checks.append("Chromium: production build, live SSE, accessible history and location")

                        # A failed sidecar save must not undo a successful semantic create.
                        before = {n["id"] for n in request("GET", "/graph")["nodes"]}
                        def fail_position(route: Any) -> None:
                            if route.request.method == "POST":
                                route.fulfill(status=503, content_type="application/json", body='{"detail":"intentional layout fault"}')
                            else:
                                route.continue_()
                        page.route("**/ui/positions/*", fail_position)
                        page.locator("canvas").click(button="right", position={"x": 900, "y": 470})
                        search = page.get_by_placeholder("Search nodes…")
                        expect(search).to_be_visible()
                        search.fill("directory")
                        expect(page.locator(".add-row").first).to_be_visible()
                        search.press("Enter")
                        expect(page.locator(".position-notice")).to_be_visible(timeout=15000)
                        expect(page.locator(".primary-status")).to_have_text("Ready", timeout=15000)
                        after = {n["id"] for n in request("GET", "/graph")["nodes"]}
                        assert len(after - before) == 1
                        page.unroute("**/ui/positions/*", fail_position)
                        def fail_graph(route: Any) -> None:
                            route.fulfill(status=503, content_type="application/json", body='{"detail":"intentional graph fault"}')
                        page.route("**/graph*", fail_graph)
                        page.get_by_role("button", name="Reload view").click()
                        expect(page.locator(".primary-status")).to_contain_text("error:", timeout=15000)
                        expect(page.locator(".position-notice")).to_be_visible()
                        page.screenshot(path=str(OUTPUT / "workspace-warning-and-error.png"))
                        page.get_by_role("button", name="Dismiss layout warning").click()
                        expect(page.locator(".position-notice")).to_have_count(0)
                        expect(page.locator(".primary-status")).to_contain_text("error:")
                        page.unroute("**/graph*", fail_graph)
                        page.get_by_role("button", name="Reload view").click()
                        expect(page.locator(".primary-status")).to_have_text("Ready", timeout=15000)
                        checks.append("Chromium: real Node retained after injected layout failure; independent error and dismiss")

                        # The ready handshake must close the missed-event gap after an actual stream outage.
                        broken.set()
                        expect(page.locator(".connection")).to_have_text("Reconnecting", timeout=15000)
                        request("POST", "/node", json={"type": "directory", "name": "Created while disconnected"})
                        expected_count = len(request("GET", "/graph")["nodes"])
                        broken.clear()
                        expect(page.locator(".connection")).to_have_text("Live", timeout=20000)
                        expect(page.locator(".counts")).to_have_attribute("aria-label", f"{expected_count} nodes, 0 edges, 0 boundary connections", timeout=15000)
                        checks.append("Chromium: real SSE outage/reconnect catches up an offline graph commit")

                        # Exercise native canvas drill-down, then capture the synthetic model graph.
                        page.locator("canvas").dblclick(position={"x": 130, "y": 120})
                        expect(page.locator('.crumb[aria-current="location"]')).to_have_text("baselines", timeout=15000)
                        page.locator("canvas").dblclick(position={"x": 130, "y": 120})
                        expect(page.locator('.crumb[aria-current="location"]')).to_have_text("Workspace demo", timeout=15000)
                        expect(page.locator(".counts")).to_have_attribute("aria-label", "4 nodes, 3 edges, 0 boundary connections")
                        page.screenshot(path=str(OUTPUT / "workspace-model.png"))
                        page.get_by_role("button", name="Back", exact=True).click()
                        expect(page.locator('.crumb[aria-current="location"]')).to_have_text("baselines", timeout=15000)
                        page.get_by_role("button", name="Forward", exact=True).click()
                        expect(page.locator('.crumb[aria-current="location"]')).to_have_text("Workspace demo", timeout=15000)
                        checks.append("Chromium: native canvas drill-down plus Back/Forward view navigation")

                        for width in [390, 768]:
                            page.set_viewport_size({"width": width, "height": 844})
                            expect(page.get_by_role("button", name="Reload view")).to_be_visible()
                            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                            assert page.locator(".topbar").evaluate("el => el.scrollWidth <= innerWidth")
                            page.get_by_role("button", name="Reload view").focus()
                            # Enter via the keyboard, not a synthetic focus after a mouse gesture.
                            page.keyboard.press("Shift+Tab")
                            page.keyboard.press("Tab")
                            expect(page.get_by_role("button", name="Reload view")).to_be_focused()
                            assert page.get_by_role("button", name="Reload view").evaluate("el => getComputedStyle(el).outlineStyle !== 'none'")
                            page.screenshot(path=str(OUTPUT / f"workspace-{width}.png"))
                        checks.append("Chromium: 390/768px toolbar layout, focus visibility, reduced-motion rendering")
                        assert not page_errors, page_errors
                    except BaseException:
                        page.screenshot(path=str(OUTPUT / "failure.png"))
                        raise
                    finally:
                        context.tracing.stop(path=str(OUTPUT / "browser-trace.zip"))
                        (OUTPUT / "browser-results.json").write_text(json.dumps({"checks": checks, "page_errors": page_errors}, indent=2), encoding="utf-8")
                        context.close()
                        browser.close()
        finally:
            broken.clear()
            server.should_exit = True
            worker.join(timeout=5)
            sock.close()
    print(json.dumps({"passed": checks, "page_errors": page_errors}, indent=2))


if __name__ == "__main__":
    run()
