"""
FinSight — Receipt scanning via OCR.
Uses pytesseract if available, falls back to basic image inspection.
"""
import os
import re
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required
from flask_wtf.csrf import validate_csrf
from wtforms import ValidationError

receipt_bp = Blueprint("receipt", __name__)

UPLOAD_FOLDER = os.path.join("static", "uploads", "receipts")
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "heic", "bmp", "gif"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_from_text(text):
    """Best-effort extraction of amount, date, merchant from raw OCR text."""
    result = {}

    # Amount: look for patterns like ₹1,234.56 / $12.50 / Rs. 500 / TOTAL 299
    amount_patterns = [
        r"(?:₹|rs\.?|inr|usd|\$|£|€)\s*([\d,]+(?:\.\d{1,2})?)",
        r"total\s*[:\-]?\s*([\d,]+(?:\.\d{1,2})?)",
        r"amount\s*[:\-]?\s*([\d,]+(?:\.\d{1,2})?)",
        r"grand\s+total\s*[:\-]?\s*([\d,]+(?:\.\d{1,2})?)",
    ]
    for pat in amount_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(",", "")
            try:
                val = float(raw)
                if 0 < val < 10_000_000:
                    result["amount"] = f"{val:.2f}"
                    break
            except ValueError:
                pass

    # Date: common formats
    date_patterns = [
        (r"(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})", "%d/%m/%Y"),
        (r"(\d{4})[\/\-](\d{2})[\/\-](\d{2})", "%Y/%m/%d"),
        (r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", "%d %B %Y"),
    ]
    for pat, fmt in date_patterns:
        m = re.search(pat, text)
        if m:
            try:
                parts = m.group(0)
                # normalise separators
                dt = datetime.strptime(parts.replace("-", "/"), fmt.replace("-", "/"))
                result["date"] = dt.strftime("%Y-%m-%d")
                break
            except (ValueError, TypeError):
                pass

    # Merchant: first non-empty line often is the store name
    lines = [l.strip() for l in text.splitlines() if l.strip() and len(l.strip()) > 2]
    if lines:
        result["merchant"] = lines[0][:60]

    return result


@receipt_bp.route("/receipt/scan", methods=["POST"])
@login_required
def scan():
    # Validate CSRF
    try:
        validate_csrf(request.form.get("csrf_token"))
    except ValidationError:
        return jsonify({"error": "CSRF validation failed"}), 400

    if "receipt" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["receipt"]
    if not file.filename or not allowed_file(file.filename):
        return jsonify({"error": "Unsupported file type"}), 400

    # Save the file
    user_folder = os.path.join(current_app.root_path, UPLOAD_FOLDER, str(current_user.id))
    os.makedirs(user_folder, exist_ok=True)

    import uuid
    ext = file.filename.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(user_folder, filename)
    file.save(filepath)

    # Try OCR
    text = ""
    try:
        from PIL import Image
        import pytesseract
        img = Image.open(filepath)
        # Enhance contrast for better OCR
        img = img.convert("L")  # grayscale
        text = pytesseract.image_to_string(img, lang="eng")
    except ImportError:
        pass  # pytesseract not installed — graceful degradation
    except Exception as e:
        current_app.logger.warning("OCR failed: %s", e)

    if text.strip():
        result = extract_from_text(text)
    else:
        result = {}

    # Always return the saved path so form can record it
    rel_path = os.path.join("uploads", "receipts", str(current_user.id), filename)
    result["receipt_path"] = rel_path.replace("\\", "/")

    if not result.get("amount"):
        result["error"] = "Could not read amount — please fill in manually"

    return jsonify(result)
