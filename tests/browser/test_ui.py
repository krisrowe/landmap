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
FIX = {"latitude": 38.7600, "longitude": -97.5850, "accuracy": 3.0}   # a mile or so from the example property, inside the region
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
        pg = ctx.new_page()
        pg.on("dialog", lambda d: d.accept())   # confirm() on delete; no prompt() exists any more
        yield pg
        browser.close()


def test_map_is_public_and_pins_need_sign_in(server, page):
    page.goto(server + "/")
    page.wait_for_selector(".leaflet-overlay-pane path", timeout=15000)   # property layers draw without a key
    page.screenshot(path=str(SHOT_DIR / "landmap-public.png"))
    assert page.is_hidden("#menu")                                      # closed until the icon is tapped
    assert page.is_hidden("#btn-pin")
    assert page.evaluate("document.querySelectorAll('.map-label').length") >= 3   # labels from the property definition
    page.click("#btn-menu")
    assert page.evaluate("document.querySelectorAll('#menu-layers input').length") >= 9
    page.click("#btn-menu")
    assert page.is_hidden("#signin-sheet")
    page.click("#btn-menu")
    assert page.is_visible("#menu-signin")
    page.click("#btn-menu")
    assert page.is_hidden("#menu")                                      # icon toggles it closed
    page.click("#btn-menu")
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
    page.wait_for_selector(".leaflet-overlay-pane path", timeout=15000)   # property layers drawn
    page.wait_for_selector("#btn-pin:not([hidden])", timeout=15000)     # key adopted, signed in
    assert "key=" not in page.url                                       # and scrubbed from the address bar

    page.click("#btn-pin")
    page.wait_for_selector("#sheet:not([hidden])", timeout=15000)
    assert f"{FIX['latitude']:.6f}" in page.text_content("#sheet-fix")
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


def test_map_stays_on_the_property(server, page):
    """Desktop context: mouse drags pan the map here; the phone emulation swallows them."""
    desk = page.context.browser.new_context(viewport={"width": 900, "height": 700})
    desk.route("**/arcgisonline.com/**", lambda r: r.abort())
    pg = desk.new_page()
    try:
        pg.goto(server + "/")
        pg.wait_for_selector(".leaflet-overlay-pane path", timeout=15000)
        assert not pg.evaluate("document.querySelector('#btn-home').classList.contains('away')")
        # Drag off the property: Home lights up; tapping it brings the property back.
        for _ in range(8):
            pg.mouse.move(450, 200); pg.mouse.down(); pg.mouse.move(450, 650, steps=8); pg.mouse.up()
            pg.wait_for_timeout(150)
        pg.wait_for_function("document.querySelector('#btn-home').classList.contains('away')", timeout=5000)
        pg.click("#btn-home")
        pg.wait_for_function("!document.querySelector('#btn-home').classList.contains('away')", timeout=5000)
        # Zooming far out for perspective also lights Home; the floor keeps the region, not the world.
        pg.mouse.move(450, 350)
        for _ in range(12):
            pg.mouse.wheel(0, 600)
            pg.wait_for_timeout(150)
        pg.wait_for_function("document.querySelector('#btn-home').classList.contains('away')", timeout=5000)
        assert pg.evaluate("document.querySelectorAll('.leaflet-overlay-pane path').length") > 0   # still the region, not the world
        pg.click("#btn-home")
        pg.wait_for_function("!document.querySelector('#btn-home').classList.contains('away')", timeout=5000)
    finally:
        desk.close()


def test_locate_shows_position(server, page):
    page.goto(server + "/")
    page.wait_for_selector(".leaflet-overlay-pane path", timeout=15000)
    page.click("#btn-locate")
    page.wait_for_selector("path[stroke='#1e88e5']", timeout=15000)   # position dot drawn
    assert "active" in page.get_attribute("#btn-locate", "class")


def test_locate_far_from_the_property_stays_put(server, page):
    """Seventy miles away, Locate must not fly to the neighborhood you're standing in."""
    far = page.context.browser.new_context(geolocation={"latitude": 37.75, "longitude": -97.60, "accuracy": 5.0},
                                           permissions=["geolocation"], viewport={"width": 420, "height": 800})
    far.route("**/arcgisonline.com/**", lambda r: r.abort())
    pg = far.new_page()
    try:
        pg.goto(server + "/?key=" + KEY)
        pg.wait_for_selector(".leaflet-overlay-pane path", timeout=15000)
        pg.click("#btn-locate")
        pg.wait_for_function("document.querySelector('#status').textContent.includes('mi south of the property')", timeout=15000)
        assert not pg.evaluate("document.querySelector('#btn-home').classList.contains('away')")   # still on the land
        assert pg.evaluate("document.querySelectorAll('.map-label').length") >= 3
        pg.click("#btn-pin")
        pg.wait_for_function("document.querySelector('#status').textContent.includes('pins are for when')", timeout=20000)
        assert pg.is_hidden("#sheet")
    finally:
        far.close()


def test_tap_a_spot_and_teleport_there(server, page):
    """Tapping the map offers Pin here / Put me here; Put me here shifts every GPS reading so
    walking at home moves you around the land, survives a reload, and ends from the toolbar."""
    page.goto(server + "/")
    page.wait_for_selector(".leaflet-overlay-pane path", timeout=15000)
    page.mouse.click(210, 300)                                            # a spot on the land, off the centre label
    page.wait_for_selector("#spot-sheet:not([hidden])", timeout=5000)
    assert page.is_hidden("#spot-pin") == page.is_hidden("#btn-pin")      # pinning offered only when signed in
    tapped = [float(v) for v in page.text_content("#spot-fix").split(",")]
    page.click("#spot-teleport")
    page.wait_for_function("document.querySelector('#status').textContent.includes('now at the spot')", timeout=15000)
    here = [float(v) for v in page.evaluate("document.body.dataset.here").split(",")]
    assert abs(here[0] - tapped[0]) < 1e-5 and abs(here[1] - tapped[1]) < 1e-5   # you are where you tapped, not at FIX
    assert page.is_visible("#btn-teleport")

    page.context.set_geolocation({"latitude": FIX["latitude"] + 0.0010, "longitude": FIX["longitude"], "accuracy": 3.0})
    page.wait_for_function(f"Math.abs(parseFloat(document.body.dataset.here.split(',')[0]) - {tapped[0] + 0.0010}) < 2e-5", timeout=15000)
    here = [float(v) for v in page.evaluate("document.body.dataset.here").split(",")]
    assert abs(here[1] - tapped[1]) < 1e-5                                 # moved north only, same ground distance

    page.reload()
    page.wait_for_selector(".leaflet-overlay-pane path", timeout=15000)
    assert page.is_visible("#btn-teleport")                               # still teleported after a reload
    page.click("#btn-teleport")
    page.wait_for_function("document.querySelector('#status').textContent.includes('Back to your real position')", timeout=5000)
    assert page.is_hidden("#btn-teleport")
    page.context.set_geolocation(FIX)
