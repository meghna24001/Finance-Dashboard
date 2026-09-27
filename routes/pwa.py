from flask import Blueprint, current_app, jsonify, send_from_directory, url_for

# Everything that lets the site behave like an installable app.
pwa = Blueprint("pwa", __name__)


@pwa.route("/manifest.webmanifest")
def manifest():
    """The app's "ID card": its name, icons and colours. Browsers read it to offer installing."""

    def icon(filename):
        return url_for("static", filename=f"icons/{filename}")

    data = {
        "id": "/",
        "name": current_app.config["APP_NAME"],
        "short_name": current_app.config["APP_SHORT_NAME"],
        "description": "Track your income, spending and budgets.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",  # open like a real app, without the browser's address bar
        "background_color": "#edf2f0",
        "theme_color": "#0a3f35",
        "categories": ["finance"],
        "icons": [
            {"src": icon("icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": icon("icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": icon("icon-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        # Long-press the app icon on Android to jump straight to these.
        "shortcuts": [
            {"name": "Add expense", "short_name": "Expense", "url": url_for("transactions.new", kind="expense")},
            {"name": "Add income", "short_name": "Income", "url": url_for("transactions.new", kind="income")},
        ],
    }
    response = jsonify(data)
    response.mimetype = "application/manifest+json"
    return response


@pwa.route("/sw.js")
def service_worker():
    """The service worker must be served from the top of the site so it covers every page."""
    response = send_from_directory(current_app.static_folder, "sw.js", mimetype="application/javascript")
    response.headers["Cache-Control"] = "no-cache"  # always check for a newer version
    response.headers["Service-Worker-Allowed"] = "/"
    return response
