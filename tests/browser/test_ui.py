"""Browser test: drives the real page in Chromium with a faked GPS fix.

Run explicitly: pytest tests/browser (excluded from the default run; needs
Playwright and a Chromium binary, PLAYWRIGHT_CHROMIUM or Playwright's own).
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

playwright = pytest.importorskip("playwright.sync_api")

KEY = "browser-" + "k" * 8
FIX = {"latitude": 45.1000, "longitude": -100.5000, "accuracy": 3.0}
SHOT_DIR = Path(os.environ.get("LANDMAP_SHOT_DIR", "/tmp"))


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    port = _free_port()
    env = dict(os.environ, LANDMAP_DATA_PATH=str(data), LANDMAP_ACCESS_KEY=KEY)
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "landmap.server:app", "--port", str(port)],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            httpx.get(base + "/healthz", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    yield base
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def page(server):
    with playwright.sync_playwright() as p:
        launch = {"headless": True}
        if os.environ.get("PLAYWRIGHT_CHROMIUM"):
            launch["executable_path"] = os.environ["PLAYWRIGHT_CHROMIUM"]
        browser = p.chromium.launch(**launch)
        ctx = browser.new_context(geolocation=FIX, permissions=["geolocation"],
                                  viewport={"width": 420, "height": 800}, is_mobile=True, has_touch=True)
        # Map tiles come from the internet; keep the test hermetic and fast.
        ctx.route("**/arcgisonline.com/**", lambda r: r.abort())
        ctx.route("**/openstreetmap.org/**", lambda r: r.abort())
        pg = ctx.new_page()
        pg.on("dialog", lambda d: d.accept())   # confirm() on delete; no prompt() exists any more
        yield pg
        browser.close()


def test_map_is_public_and_pins_need_sign_in(server, page):
    page.goto(server + "/")
    page.wait_for_selector("path.leaflet-interactive", timeout=15000)   # boundary draws without a key
    page.screenshot(path=str(SHOT_DIR / "landmap-public.png"))
    assert page.is_hidden("#btn-pin")
    assert page.is_hidden("#signin-sheet")
    page.click("#btn-menu")
    assert page.is_visible("#menu-signin")
    page.click("#menu-signin")
    page.fill("#signin-key", "not-the-key")
    page.click("#signin-form button[type=submit]")
    page.wait_for_function("document.querySelector('#status').textContent.includes('not accepted')", timeout=10000)
    assert page.is_hidden("#btn-pin")
    page.click("#btn-menu")
    page.click("#menu-signin")
    page.fill("#signin-key", KEY)
    page.click("#signin-form button[type=submit]")
    page.wait_for_selector("#btn-pin:not([hidden])", timeout=10000)
    page.click("#btn-menu")
    page.click("#menu-signout")
    page.wait_for_selector("#btn-pin", state="hidden", timeout=10000)


def test_boundary_and_gps_pinning(server, page):
    page.goto(server + "/?key=" + KEY)                                  # the link saved to the home screen
    page.wait_for_selector("path.leaflet-interactive", timeout=15000)   # boundary polygon drawn
    page.wait_for_selector("#btn-pin:not([hidden])", timeout=15000)     # key adopted, signed in
    assert "key=" not in page.url                                       # and scrubbed from the address bar

    page.click("#btn-pin")
    page.wait_for_selector("#sheet:not([hidden])", timeout=15000)
    assert "45.100000" in page.text_content("#sheet-fix")
    page.fill("#pin-label", "NE corner pin")
    page.fill("#pin-note", "orange flag")
    page.click("#pin-form button[type=submit]")
    page.wait_for_selector(".pin-label:not(.pending)", timeout=10000)
    assert page.text_content(".pin-label").strip() == "NE corner pin"

    pins = httpx.get(server + "/api/pins", headers={"x-access-key": KEY}).json()
    assert len(pins) == 1
    assert pins[0]["label"] == "NE corner pin" and pins[0]["accuracy"] == 3.0
    assert abs(pins[0]["lat"] - FIX["latitude"]) < 1e-6

    page.screenshot(path=str(SHOT_DIR / "landmap-pinned.png"))

    # Survives a reload (the stored key signs in silently; pins come from the server, not the queue).
    # Locate pans to the fix, which is where the pin is, so the marker is on screen for the popup steps.
    page.reload()
    page.wait_for_selector(".pin-label:not(.pending)", timeout=15000)
    page.click("#btn-locate")
    page.wait_for_selector(".leaflet-interactive[stroke='#e0a82e']", state="visible", timeout=15000)

    # Edit through the marker popup.
    page.click(".leaflet-interactive[stroke='#e0a82e']")
    page.wait_for_selector(".popup-actions button[data-act=edit]")
    page.click(".popup-actions button[data-act=edit]")
    page.fill("#pin-label", "NE corner")
    page.click("#pin-form button[type=submit]")
    page.wait_for_function("document.querySelector('.pin-label').textContent.trim() === 'NE corner'", timeout=10000)

    # Delete it.
    page.click(".leaflet-interactive[stroke='#e0a82e']")
    page.wait_for_selector(".popup-actions button[data-act=delete]")
    page.click(".popup-actions button[data-act=delete]")
    page.wait_for_function("document.querySelectorAll('.pin-label').length === 0", timeout=10000)
    assert httpx.get(server + "/api/pins", headers={"x-access-key": KEY}).json() == []


def test_locate_shows_position(server, page):
    page.goto(server + "/")
    page.wait_for_selector("path.leaflet-interactive", timeout=15000)
    page.click("#btn-locate")
    page.wait_for_selector("path[stroke='#1e88e5']", timeout=15000)   # position dot drawn
    assert "active" in page.get_attribute("#btn-locate", "class")
