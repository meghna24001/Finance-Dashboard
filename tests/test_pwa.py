"""Checks the parts that make the site installable: manifest, icons, service worker.
Uses a throwaway in-memory database, so your real data is never touched."""
import json
import re
import struct

from app import create_app
from config import TestConfig
from tests.helpers import check, finish, signup, text

app = create_app(TestConfig)
anon = app.test_client()


def png_size(data):
    """Width and height, read from the first bytes of a PNG file."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return struct.unpack(">II", data[16:24])


# ---- manifest
r = anon.get("/manifest.webmanifest")
m = json.loads(r.get_data(as_text=True))
check("The manifest is public and served as a web manifest", r.status_code == 200 and r.mimetype == "application/manifest+json")
check("It has a name, short name, and opens as a standalone app", m["name"] == "FinSight" and m["short_name"] == "FinSight" and m["display"] == "standalone")
check("It starts at / and covers the whole site", m["start_url"] == "/" and m["scope"] == "/" and m["id"] == "/")
check("It has theme and background colours", re.fullmatch(r"#[0-9a-f]{6}", m["theme_color"]) and re.fullmatch(r"#[0-9a-f]{6}", m["background_color"]))
purposes = {(i["sizes"], i["purpose"]) for i in m["icons"]}
check("It lists 192px and 512px icons plus a maskable one", {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= purposes)
for icon in m["icons"]:
    got = anon.get(icon["src"])
    w, h = png_size(got.data)
    check(f"Icon {icon['src']} exists and really is {icon['sizes']}", got.status_code == 200 and f"{w}x{h}" == icon["sizes"] and icon["type"] == "image/png")
check("Both shortcuts point at real pages", all(anon.get(s["url"]).status_code in (200, 302) for s in m["shortcuts"]) and len(m["shortcuts"]) == 2)

# ---- the other icons
for name, size in [("apple-touch-icon.png", (180, 180)), ("favicon-32.png", (32, 32))]:
    got = anon.get(f"/static/icons/{name}")
    check(f"{name} exists at {size[0]}x{size[1]}", got.status_code == 200 and png_size(got.data) == size)
svg = anon.get("/static/icons/icon.svg")
check("icon.svg exists", svg.status_code == 200 and b"<svg" in svg.data)

# ---- service worker
r = anon.get("/sw.js")
sw = r.get_data(as_text=True)
check("The service worker is public and served as JavaScript from the top of the site", r.status_code == 200 and "javascript" in r.mimetype)
check("It is never cached, so updates are noticed", r.headers["Cache-Control"] == "no-cache" and r.headers["Service-Worker-Allowed"] == "/")
precache = json.loads(re.sub(r",\s*\]", "]", re.search(r"const PRECACHE = (\[.*?\]);", sw, re.S).group(1)))  # JavaScript allows a trailing comma, JSON does not
check("It precaches static assets", len(precache) >= 1 and all(p.startswith("/static/") for p in precache))
for path in precache:
    check(f"Precached file {path} exists (a missing one would break installing)", anon.get(path).status_code == 200)
check("It only handles requests from the same site", "url.origin !== self.location.origin" in sw)

# ---- offline page must not exist (online-only mode)
r = anon.get("/offline")
check("The /offline route is removed (online-only mode)", r.status_code == 404)

# ---- every page is set up to be installed
signup(anon)
for url in ["/dashboard", "/transactions", "/profile"]:
    html = text(anon.get(url))
    check(f"{url} links the manifest, icons and app script", all(x in html for x in ['rel="manifest"', 'rel="apple-touch-icon"', "js/pwa.js", 'name="theme-color"', 'apple-mobile-web-app-capable']))
login_html = text(app.test_client().get("/login"))
check("The sign-in page (before login) is installable too", 'rel="manifest"' in login_html and "js/pwa.js" in login_html)

# ---- install box on the profile page
profile = text(anon.get("/profile"))
check("Profile page has the Install the app box", "data-install-panel" in profile and "data-install-button" in profile and "Add to Home Screen" in profile)
check("The install button starts hidden", re.search(r"<button[^>]*data-install-button hidden", profile) is not None)
check("Other pages don't have the install box", "data-install-panel" not in text(anon.get("/dashboard")))
check("Profile page no longer has the offline toggle (online-only mode)", "data-offline-toggle" not in profile and "data-offline-panel" not in profile)

# ---- privacy: browsers must not keep copies of pages
for url in ["/dashboard", "/transactions", "/profile", "/budgets"]:
    check(f"{url} is sent with 'no-store'", anon.get(url).headers.get("Cache-Control") == "no-store")
check("Sign-in page is 'no-store' too", app.test_client().get("/login").headers.get("Cache-Control") == "no-store")
check("Static files are not marked no-store, so they can be reused", "no-store" not in (anon.get("/static/css/style.css").headers.get("Cache-Control") or ""))

finish()
