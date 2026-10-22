import json
import os
import sqlite3
from functools import wraps

from flask import (
    Flask,
    request,
    jsonify,
    session,
    send_from_directory,
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash


# ==================================================
# 1. ASOSIY SOZLAMALAR
# ==================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.environ.get(
    "POS_DB_PATH",
    os.path.join(BASE_DIR, "techmir_pos.sqlite3")
)

POS_PASSWORD = os.environ.get("POS_PASSWORD", "Asqar-7484")

SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-before-deploying"
)

app = Flask(__name__, static_folder=None)

app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1
)

app.secret_key = SECRET_KEY

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1") == "1",
    MAX_CONTENT_LENGTH=25 * 1024 * 1024,
)


# ==================================================
# 2. MA'LUMOTLAR BAZASI
# ==================================================

def db_connect():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db_connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS app_state (
                id INTEGER PRIMARY KEY CHECK(id=1),
                products TEXT,
                sales TEXT,
                settings TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        con.execute("""
            INSERT OR IGNORE INTO app_state
                (id, products, sales, settings)
            VALUES (1, NULL, NULL, NULL)
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS app_auth (
                id INTEGER PRIMARY KEY CHECK(id=1),
                password_hash TEXT NOT NULL
            )
        """)

        con.execute("""
            INSERT OR IGNORE INTO app_auth (id, password_hash)
            VALUES (1, ?)
        """, (generate_password_hash(POS_PASSWORD),))


# ==================================================
# 3. KIRISH TEKSHIRUVI
# ==================================================

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            return jsonify({
                "error": "login_required"
            }), 401

        return fn(*args, **kwargs)

    return wrapped


# ==================================================
# 4. HTML BOSH SAHIFASI
# ==================================================

@app.get("/")
def index():
    # HTML faylingizni quyidagi nomlardan biri bilan saqlashingiz mumkin.
    html_candidates = [
        "TechMirUz_telefon_menyu_toliq.html",
        "TechMirUz_telefon_menyu_toliq(1).html",
        "index.html",
        "index(1).html",
    ]

    for filename in html_candidates:
        filepath = os.path.join(BASE_DIR, filename)

        if os.path.isfile(filepath):
            return send_from_directory(BASE_DIR, filename)

    return jsonify({
        "error": "HTML fayl topilmadi",
        "message": "HTML faylni app.py bilan bir papkaga joylashtiring.",
        "expected_files": html_candidates
    }), 500


# ==================================================
# 5. SERVER ISHLAYOTGANINI TEKSHIRISH
# ==================================================

@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "app": "TechMir POS"
    })


# ==================================================
# 6. TIZIMGA KIRISH
# ==================================================

@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    password = str(data.get("password", ""))

    with db_connect() as con:
        row = con.execute(
            "SELECT password_hash FROM app_auth WHERE id=1"
        ).fetchone()

    if not row or not check_password_hash(
        row["password_hash"], password
    ):
        return jsonify({
            "error": "invalid_password",
            "message": "Parol noto‘g‘ri."
        }), 401

    session.clear()
    session["authenticated"] = True

    return jsonify({"ok": True})


# ==================================================
# 7. PAROLNI ALMASHTIRISH
# ==================================================

@app.post("/api/change-password")
@login_required
def change_password():
    data = request.get_json(silent=True) or {}

    current_password = str(data.get("current_password", ""))
    new_password = str(data.get("new_password", ""))

    if len(new_password) < 6:
        return jsonify({
            "error": "Yangi parol kamida 6 ta belgidan iborat bo‘lsin."
        }), 400

    if current_password == new_password:
        return jsonify({
            "error": "Yangi parol joriy paroldan farq qilishi kerak."
        }), 400

    with db_connect() as con:
        row = con.execute(
            "SELECT password_hash FROM app_auth WHERE id=1"
        ).fetchone()

        if not row or not check_password_hash(
            row["password_hash"], current_password
        ):
            return jsonify({
                "error": "Joriy parol noto‘g‘ri."
            }), 401

        con.execute(
            "UPDATE app_auth SET password_hash=? WHERE id=1",
            (generate_password_hash(new_password),)
        )

    return jsonify({
        "ok": True,
        "message": "Parol muvaffaqiyatli almashtirildi."
    })


# ==================================================
# 8. TIZIMDAN CHIQISH
# ==================================================

@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


# ==================================================
# 9. MAHSULOTLAR VA SAVDOLARNI OLISH
# ==================================================

@app.get("/api/state")
@login_required
def get_state():
    with db_connect() as con:
        row = con.execute("""
            SELECT products, sales, settings, updated_at
            FROM app_state
            WHERE id=1
        """).fetchone()

    return jsonify({
        "products": json.loads(row["products"])
            if row["products"] else None,

        "sales": json.loads(row["sales"])
            if row["sales"] else [],

        "settings": json.loads(row["settings"])
            if row["settings"] else None,

        "updated_at": row["updated_at"]
    })


# ==================================================
# 10. MAHSULOTLAR VA SAVDOLARNI SAQLASH
# ==================================================

@app.post("/api/state")
@login_required
def save_state():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "invalid_state"}), 400

    products = data.get("products")
    sales = data.get("sales")
    settings = data.get("settings")

    if (
        not isinstance(products, list)
        or not isinstance(sales, list)
        or not isinstance(settings, dict)
    ):
        return jsonify({
            "error": "invalid_state",
            "message": "Mahsulotlar, savdolar yoki sozlamalar formati noto‘g‘ri."
        }), 400

    products_json = json.dumps(
        products, ensure_ascii=False, separators=(",", ":")
    )

    sales_json = json.dumps(
        sales, ensure_ascii=False, separators=(",", ":")
    )

    settings_json = json.dumps(
        settings, ensure_ascii=False, separators=(",", ":")
    )

    with db_connect() as con:
        con.execute("""
            UPDATE app_state
            SET products=?,
                sales=?,
                settings=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=1
        """, (
            products_json,
            sales_json,
            settings_json
        ))

    return jsonify({"ok": True})


# ==================================================
# 11. KATTA RASM YOKI SO‘ROV XATOSI
# ==================================================

@app.errorhandler(413)
def too_large(_error):
    return jsonify({
        "error": "request_too_large",
        "message": "Rasm yoki ma'lumot hajmi juda katta."
    }), 413


# ==================================================
# 12. TOPILMAGAN MANZIL
# ==================================================

@app.errorhandler(404)
def not_found(_error):
    return jsonify({
        "error": "not_found",
        "message": "Bu manzil topilmadi."
    }), 404


# ==================================================
# 13. SERVERNI ISHGA TUSHIRISH
# ==================================================

init_db()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        debug=False
    )
