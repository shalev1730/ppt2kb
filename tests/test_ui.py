"""
Browser tests of the web UI (headless Chromium through Playwright): Dark Mode toggle and
persistence, RTL/LTR layouts, the image output mode selector. Skipped when Playwright or its
Chromium is not installed (``pip install playwright && playwright install chromium``).
"""
from __future__ import annotations

import pytest

from conftest import _Server, _free_port

pw = pytest.importorskip("playwright.sync_api")

DARK_BG = "rgb(15, 17, 23)"     # #0F1117
LIGHT_BG = "rgb(244, 246, 249)"  # #f4f6f9


@pytest.fixture
def ui_server(app_settings):
    from ppt2kb.app import create_app

    srv = _Server(create_app(app_settings), _free_port()).start()
    yield srv
    srv.stop()


@pytest.fixture
def browser():
    try:
        with pw.sync_playwright() as p:
            b = p.chromium.launch()
            yield b
            b.close()
    except Exception as e:  # pragma: no cover - environment without a browser
        pytest.skip(f"Chromium not available for Playwright: {e.__class__.__name__}")


def _bg(page):
    return page.evaluate("getComputedStyle(document.body).backgroundColor")


def test_dark_mode_toggle_and_persistence(ui_server, browser):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, color_scheme="light")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(ui_server.base + "/#/upload")
    page.wait_for_selector("#upload-mode")
    assert page.get_attribute("html", "data-theme") == "light" and _bg(page) == LIGHT_BG
    btn = page.locator("#theme-toggle")
    assert btn.get_attribute("aria-pressed") == "false" and "dark" in btn.get_attribute("aria-label").lower()
    # one click -> dark, applied to the whole page (body, cards, inputs), stored per browser
    btn.click()
    assert page.get_attribute("html", "data-theme") == "dark" and _bg(page) == DARK_BG
    assert page.evaluate("getComputedStyle(document.querySelector('.card')).backgroundColor") == "rgb(26, 29, 39)"
    assert page.evaluate("getComputedStyle(document.querySelector('#title')).backgroundColor") == "rgb(36, 41, 54)"
    assert page.evaluate("getComputedStyle(document.body).color") == "rgb(241, 245, 249)"
    assert page.evaluate("localStorage.getItem('ppt2kb.theme')") == "dark"
    assert btn.get_attribute("aria-pressed") == "true"
    # survives a reload (applied before first paint by theme.js) and navigation to every view
    page.reload()
    page.wait_for_selector("#upload-mode")
    assert page.get_attribute("html", "data-theme") == "dark" and _bg(page) == DARK_BG
    for route in ("#/jobs", "#/settings"):
        page.goto(ui_server.base + "/" + route)
        page.wait_for_timeout(300)
        assert _bg(page) == DARK_BG
        # no element left with a hard-coded white surface (slide renders are excluded by design)
        white = page.evaluate("""() => Array.from(document.querySelectorAll('main *, header *')).filter(e => {
            const cs = getComputedStyle(e); return cs.backgroundColor === 'rgb(255, 255, 255)' && !e.closest('.slide-image');
        }).map(e => e.tagName + '.' + e.className).slice(0, 5)""")
        assert white == [], white
    # and back to light
    page.locator("#theme-toggle").click()
    assert page.get_attribute("html", "data-theme") == "light" and page.evaluate("localStorage.getItem('ppt2kb.theme')") == "light"
    # a browser with no stored choice follows the system preference
    ctx2 = browser.new_context(viewport={"width": 1280, "height": 900}, color_scheme="dark")
    p2 = ctx2.new_page()
    p2.goto(ui_server.base + "/#/upload")
    p2.wait_for_selector("#upload-mode")
    assert p2.get_attribute("html", "data-theme") == "dark"
    ctx2.close()
    assert errors == []
    ctx.close()


def test_rtl_and_ltr_layouts_keep_the_toggle_top_right(ui_server, browser):
    ctx = browser.new_context(viewport={"width": 1200, "height": 800})
    page = ctx.new_page()
    page.goto(ui_server.base + "/#/upload")
    page.wait_for_selector("#upload-mode")
    for expected_dir, click in (("ltr", False), ("rtl", True), ("ltr", True)):
        if click:
            page.locator("#lang-toggle").click()
            page.wait_for_timeout(200)
        assert page.get_attribute("html", "dir") == expected_dir
        box = page.locator("#theme-toggle").bounding_box()
        assert box["x"] + box["width"] > 1200 - 40 and box["y"] < 60, (expected_dir, box)  # top-right in both directions
        # the toggle does not overlap the header controls
        for sel in ("#lang-toggle", "#health", ".brand"):
            other = page.locator(sel).bounding_box()
            overlap = not (box["x"] >= other["x"] + other["width"] or other["x"] >= box["x"] + box["width"])
            assert not overlap, (expected_dir, sel, box, other)
        # the mode selector is translated and still shows three choices, default Embedded Images + Full Slides
        labels = page.locator("#upload-mode .mode-option strong").all_inner_texts()
        assert len(labels) == 3
        assert labels == (["תמונות בלבד", "תמונות ושקופיות", "שקופיות בלבד"] if expected_dir == "rtl" else ["Embedded Images Only", "Embedded Images + Full Slides", "Full Slides Only"])
        assert page.locator('#upload-mode input[name="image_mode"]:checked').get_attribute("value") == "embedded_full"
        # dark mode works in this direction too
        page.locator("#theme-toggle").click()
        assert _bg(page) == DARK_BG
        page.locator("#theme-toggle").click()
        assert _bg(page) == LIGHT_BG
    ctx.close()
