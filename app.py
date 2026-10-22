import json
import os
import sqlite3
import hashlib
import base64
import io
import time
import urllib.request
import urllib.error
import hmac
import secrets
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("POS_DB_PATH", os.path.join(BASE_DIR, "techmir_pos.sqlite3"))
POS_PASSWORD = os.environ.get("POS_PASSWORD", "Asqar-7484")
SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-secret-before-deploying")
PAYME_MERCHANT_ID = os.environ.get("PAYME_MERCHANT_ID", "").strip()
PAYME_SECRET_KEY = os.environ.get("PAYME_SECRET_KEY", "").strip()
PAYME_CALLBACK_URL = os.environ.get("PAYME_CALLBACK_URL", "").strip()
PAYME_RESPONSE_URL = os.environ.get("PAYME_RESPONSE_URL", "").strip()
PAYME_CHECKOUT_ENDPOINT = "https://pay.payme.uz/api/checkout/url"

app = Flask(__name__, static_folder=None)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.secret_key = SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1") == "1",
    MAX_CONTENT_LENGTH=25 * 1024 * 1024,
)


def db_connect():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db_connect() as con:
        con.execute("CREATE TABLE IF NOT EXISTS app_state (id INTEGER PRIMARY KEY CHECK(id=1), products TEXT, sales TEXT, settings TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        con.execute("INSERT OR IGNORE INTO app_state (id, products, sales, settings) VALUES (1, NULL, NULL, NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS app_auth (id INTEGER PRIMARY KEY CHECK(id=1), password_hash TEXT NOT NULL)")
        # Birinchi ishga tushishda joriy POS_PASSWORD qiymatini boshlang'ich parol sifatida saqlaydi.
        con.execute(
            "INSERT OR IGNORE INTO app_auth (id, password_hash) VALUES (1, ?)",
            (generate_password_hash(POS_PASSWORD),)
        )
        con.execute("""CREATE TABLE IF NOT EXISTS payme_orders (
            order_id TEXT PRIMARY KEY,
            amount_sum INTEGER NOT NULL,
            amount_tiyin INTEGER NOT NULL,
            checkout_url TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            paid_at TEXT
        )""")


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            return jsonify({"error": "login_required"}), 401
        return fn(*args, **kwargs)
    return wrapped


@app.get("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    with db_connect() as con:
        row = con.execute("SELECT password_hash FROM app_auth WHERE id=1").fetchone()
    if not row or not check_password_hash(row["password_hash"], str(data.get("password", ""))):
        return jsonify({"error": "invalid_password"}), 401
    session.clear()
    session["authenticated"] = True
    return jsonify({"ok": True})



@app.post("/api/change-password")
@login_required
def change_password():
    data = request.get_json(silent=True) or {}
    current_password = str(data.get("current_password", ""))
    new_password = str(data.get("new_password", ""))

    if len(new_password) < 1:
        return jsonify({"error": "Yangi parol kamida 1 ta belgidan iborat bo‘lsin."}), 400
    if current_password == new_password:
        return jsonify({"error": "Yangi parol joriy paroldan farq qilishi kerak."}), 400

    with db_connect() as con:
        row = con.execute("SELECT password_hash FROM app_auth WHERE id=1").fetchone()
        if not row or not check_password_hash(row["password_hash"], current_password):
            return jsonify({"error": "Joriy parol noto‘g‘ri."}), 401
        con.execute(
            "UPDATE app_auth SET password_hash=? WHERE id=1",
            (generate_password_hash(new_password),)
        )

    return jsonify({"ok": True, "message": "Parol muvaffaqiyatli almashtirildi."})

@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/state")
@login_required
def get_state():
    with db_connect() as con:
        row = con.execute("SELECT products, sales, settings, updated_at FROM app_state WHERE id=1").fetchone()
    return jsonify({
        "products": json.loads(row["products"]) if row["products"] else None,
        "sales": json.loads(row["sales"]) if row["sales"] else [],
        "settings": json.loads(row["settings"]) if row["settings"] else None,
        "updated_at": row["updated_at"],
    })


@app.post("/api/state")
@login_required
def save_state():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("products"), list) or not isinstance(data.get("sales"), list) or not isinstance(data.get("settings"), dict):
        return jsonify({"error": "invalid_state"}), 400
    products = json.dumps(data["products"], ensure_ascii=False, separators=(",", ":"))
    sales = json.dumps(data["sales"], ensure_ascii=False, separators=(",", ":"))
    settings = json.dumps(data["settings"], ensure_ascii=False, separators=(",", ":"))
    with db_connect() as con:
        con.execute("UPDATE app_state SET products=?, sales=?, settings=?, updated_at=CURRENT_TIMESTAMP WHERE id=1", (products, sales, settings))
    return jsonify({"ok": True})



def payme_signature(secret, params):
    """Payme API signature: secret + non-empty params sorted by key, joined by |."""
    parts = [secret]
    for key in sorted(params):
        if key in ("signature", "response_signature_string"):
            continue
        value = params[key]
        if value is None or value == "":
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        parts.append(str(value))
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def make_qr_data_uri(url):
    qr = qrcode.QRCode(box_size=7, border=3)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


@app.post("/api/payme/create")
@login_required
def payme_create_order():
    if not PAYME_MERCHANT_ID or not PAYME_SECRET_KEY or not PAYME_CALLBACK_URL:
        return jsonify({
            "error": "payme_not_configured",
            "message": "Payme sozlanmagan. PAYME_MERCHANT_ID, PAYME_SECRET_KEY va PAYME_CALLBACK_URL qiymatlarini server muhitida kiriting."
        }), 503
    if not PAYME_CALLBACK_URL.startswith("https://"):
        return jsonify({"error": "invalid_callback_url", "message": "PAYME_CALLBACK_URL ochiq HTTPS manzil bo‘lishi kerak."}), 400

    data = request.get_json(silent=True) or {}
    try:
        amount_sum = int(data.get("amount_sum", 0))
    except (TypeError, ValueError):
        amount_sum = 0
    if amount_sum < 1 or amount_sum > 1_000_000_000:
        return jsonify({"error": "invalid_amount", "message": "To‘lov summasi noto‘g‘ri."}), 400

    order_id = "TM" + str(int(time.time())) + secrets.token_hex(4).upper()
    # Payme checkout API amount is expressed in minor units (tiyin) for UZS.
    amount_tiyin = amount_sum * 100
    params = {
        "order_id": order_id,
        "merchant_id": int(PAYME_MERCHANT_ID),
        "order_desc": "TechMirUz POS buyurtma " + order_id,
        "amount": amount_tiyin,
        "currency": "UZS",
        "server_callback_url": PAYME_CALLBACK_URL,
        "lifetime": 1800,
        "lang": "uz",
    }
    if PAYME_RESPONSE_URL:
        params["response_url"] = PAYME_RESPONSE_URL
    params["signature"] = payme_signature(PAYME_SECRET_KEY, params)
    body = json.dumps({"request": params}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        PAYME_CHECKOUT_ENDPOINT, data=body,
        headers={"Content-Type": "application/json; charset=UTF-8"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        app.logger.exception("Payme checkout URL request failed")
        return jsonify({"error": "payme_unavailable", "message": "Payme bilan bog‘lanib bo‘lmadi. Keyinroq urinib ko‘ring."}), 502

    result = payload.get("response", {})
    checkout_url = result.get("checkout_url")
    if result.get("response_status") != "success" or not checkout_url:
        app.logger.warning("Payme rejected checkout request: %s", result.get("error_code", "unknown"))
        return jsonify({"error": "payme_checkout_failed", "message": result.get("error_message", "Payme to‘lov sahifasini yaratmadi.")}), 502

    with db_connect() as con:
        con.execute(
            "INSERT INTO payme_orders (order_id, amount_sum, amount_tiyin, checkout_url, status) VALUES (?, ?, ?, ?, 'pending')",
            (order_id, amount_sum, amount_tiyin, checkout_url)
        )
    return jsonify({"ok": True, "order_id": order_id, "checkout_url": checkout_url,
                    "qr_data_uri": make_qr_data_uri(checkout_url), "amount_sum": amount_sum,
                    "status": "pending"})


@app.post("/api/payme/callback")
def payme_callback():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not PAYME_SECRET_KEY:
        return jsonify({"ok": False, "message": "Invalid callback"}), 400
    supplied = str(data.get("signature", ""))
    expected = payme_signature(PAYME_SECRET_KEY, data)
    if not supplied or not hmac.compare_digest(supplied.lower(), expected.lower()):
        app.logger.warning("Payme callback signature validation failed")
        return jsonify({"ok": False, "message": "Invalid signature"}), 403
    try:
        merchant_id = int(data.get("merchant_id", 0))
        callback_amount = int(data.get("amount", -1))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Invalid payment parameters"}), 400
    if not PAYME_MERCHANT_ID or merchant_id != int(PAYME_MERCHANT_ID):
        return jsonify({"ok": False, "message": "Merchant mismatch"}), 403

    order_id = str(data.get("order_id", ""))
    status = str(data.get("order_status", "")).lower()
    with db_connect() as con:
        order = con.execute("SELECT amount_tiyin, status FROM payme_orders WHERE order_id=?", (order_id,)).fetchone()
        if not order:
            return jsonify({"ok": False, "message": "Unknown order"}), 404
        if callback_amount != order["amount_tiyin"]:
            return jsonify({"ok": False, "message": "Amount mismatch"}), 400
        if status == "approved":
            con.execute("UPDATE payme_orders SET status='paid', paid_at=CURRENT_TIMESTAMP WHERE order_id=?", (order_id,))
        elif status in ("declined", "expired", "reversed") and order["status"] != "paid":
            con.execute("UPDATE payme_orders SET status=? WHERE order_id=?", (status, order_id))
    return jsonify({"ok": True}), 200


@app.get("/api/payme/status")
@login_required
def payme_order_status():
    order_id = str(request.args.get("order_id", ""))[:100]
    with db_connect() as con:
        row = con.execute("SELECT order_id, amount_sum, status, paid_at FROM payme_orders WHERE order_id=?", (order_id,)).fetchone()
    if not row:
        return jsonify({"error": "order_not_found"}), 404
    return jsonify({"order_id": row["order_id"], "amount_sum": row["amount_sum"], "status": row["status"], "paid_at": row["paid_at"]})

@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "request_too_large", "message": "Rasm yoki ma'lumot hajmi juda katta"}), 413


init_db()

if __name__ == "__main__":
    # Local testing only. For internet deployment use a production WSGI server such as gunicorn.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=False)
