import json
import os
import sqlite3
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("POS_DB_PATH", os.path.join(BASE_DIR, "techmir_pos.sqlite3"))
POS_PASSWORD = os.environ.get("POS_PASSWORD", "Asqar-7484")
SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-secret-before-deploying")

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
    if str(data.get("password", "")) != POS_PASSWORD:
        return jsonify({"error": "invalid_password"}), 401
    session.clear()
    session["authenticated"] = True
    return jsonify({"ok": True})


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


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "request_too_large", "message": "Rasm yoki ma'lumot hajmi juda katta"}), 413


init_db()

if __name__ == "__main__":
    # Local testing only. For internet deployment use a production WSGI server such as gunicorn.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=False)
