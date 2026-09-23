"""Exercise the shipped FileViewer sanitizer on a disposable registered file.

Uses real FastAPI responses and the production Svelte bundle. It never opens a
user project or calls a model. Build frontend and install the backend, Playwright
and Chromium before running, as in workspace_browser_smoke.py.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import uvicorn
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import expect, sync_playwright

from simulanka.layout import init_project
from simulanka.layout.file_registry import create_file
from simulanka.server.app import create_app

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "security-evidence"
MARKDOWN = """# Safe document

**Formatting survives.** [Reference](#reference)

<script>window.__securityProbe = 1</script>
<img src="/__security_missing_image" onerror="window.__securityProbe = 2">
<svg onload="window.__securityProbe = 3"></svg>
<a href="javascript:window.__securityProbe=4">Unsafe action</a>
<iframe srcdoc="<script>parent.__securityProbe=5</script>"></iframe>

```html
<img src=x onerror=window.__securityProbe=6>
```
"""


def run() -> None:
    OUTPUT.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="simulanka-markdown-") as project:
        layout = init_project(Path(project)).layout
        created = create_file(layout, "doc", "sanitizer-check", MARKDOWN.encode())
        app = create_app(layout)
        app.mount("/", StaticFiles(directory=ROOT / "frontend" / "dist", html=True))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
            config = uvicorn.Config(app, log_level="warning", timeout_graceful_shutdown=2)
            server = uvicorn.Server(config)
            worker = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
            worker.start()
            try:
                deadline = time.monotonic() + 15
                while not server.started:
                    if time.monotonic() > deadline or not worker.is_alive():
                        raise RuntimeError("Disposable server did not start")
                    time.sleep(0.05)
                with httpx.Client(base_url=origin, timeout=15) as api:
                    response = api.get("/graph")
                    response.raise_for_status()
                    roots = sorted(response.json()["nodes"], key=lambda n: n["name"] != "docs")
                    docs_id = next(n["id"] for n in roots if n["name"] == "docs")
                    root_positions = {
                        n["id"]: [70 + (i % 3) * 320, 110 + (i // 3) * 160]
                        for i, n in enumerate(roots)
                    }
                    for root, positions in [
                        ("top", root_positions),
                        (docs_id, {created.node_id: [70, 110]}),
                    ]:
                        saved = api.post(f"/ui/positions/{root}", json=positions)
                        saved.raise_for_status()
                    raw = api.get("/file/content", params={"node": created.node_id})
                    raw.raise_for_status()
                    assert raw.json()["content"] == MARKDOWN

                with sync_playwright() as p:
                    browser = p.chromium.launch()
                    context = browser.new_context(viewport={"width": 1280, "height": 900})
                    context.add_init_script("window.__securityProbe = 0")
                    context.tracing.start(screenshots=True, snapshots=True, sources=True)
                    page = context.new_page()
                    errors: list[str] = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    # Block external requests: only the disposable server may be read.
                    page.route("**/*", lambda route: route.continue_()
                               if route.request.url.startswith(origin + "/") else route.abort())
                    try:
                        page.goto(origin, wait_until="domcontentloaded")
                        expect(page.locator(".primary-status")).to_have_text("Ready", timeout=15000)
                        page.locator("canvas").dblclick(position={"x": 130, "y": 120})
                        expect(page.locator('.crumb[aria-current="location"]')).to_have_text(
                            "docs", timeout=15000,
                        )
                        page.locator("canvas").click(position={"x": 130, "y": 120})
                        page.get_by_role("button", name="Files", exact=True).click()
                        viewer = page.get_by_role("complementary", name="file viewer")
                        expect(viewer.get_by_role("heading", name="Safe document")).to_be_visible()
                        markdown = viewer.locator(".markdown")
                        expect(markdown.locator("strong")).to_have_text("Formatting survives.")
                        expect(markdown.get_by_role("link", name="Reference")).to_have_attribute(
                            "href", "#reference",
                        )
                        expect(markdown.locator("pre code")).to_contain_text(
                            "onerror=window.__securityProbe=6",
                        )
                        assert markdown.locator("script, iframe, object, embed").count() == 0
                        assert markdown.evaluate(r"""el => [...el.querySelectorAll('*')].every(
                            n => [...n.attributes].every(a => !/^on/i.test(a.name)
                            && !/^\s*javascript:/i.test(a.value)))""")
                        expect(markdown.get_by_text("Unsafe action", exact=True)).not_to_have_attribute(
                            "href", "javascript:window.__securityProbe=4",
                        )
                        page.wait_for_function(
                            "[...document.querySelectorAll('.markdown img')].every(img => img.complete)",
                        )
                        assert page.evaluate("window.__securityProbe") == 0
                        assert not errors, errors
                        page.screenshot(path=str(OUTPUT / "markdown-safety.png"))
                        (OUTPUT / "markdown-safety.json").write_text(json.dumps({
                            "passed": True,
                            "checks": [
                                "real registered file response", "actual production FileViewer",
                                "safe Markdown formatting and code retained",
                                "script/iframe and event handlers removed", "javascript URL removed",
                                "no fixture script executed", "no page errors",
                            ],
                            "page_errors": errors,
                        }, indent=2), encoding="utf-8")
                    except BaseException:
                        page.screenshot(path=str(OUTPUT / "markdown-failure.png"))
                        raise
                    finally:
                        context.tracing.stop(path=str(OUTPUT / "markdown-trace.zip"))
                        context.close()
                        browser.close()
            finally:
                server.should_exit = True
                worker.join(timeout=5)


if __name__ == "__main__":
    run()
