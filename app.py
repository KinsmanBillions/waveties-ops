#!/usr/bin/env python3
"""
WaveTies Logistics – Invoice Web App (Full)
Features: Admin/Worker auth (hashed), mark paid, customers, reports,
          email invoice, WhatsApp share, deployment-ready.
"""

import sys
import os
import json
import secrets
import sqlite3
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from collections import defaultdict

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, send_file, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from invoice_generator import (
    generate_invoice, generate_receipt, create_receipt_for_payment,
    load_db, save_db, create_invoice,
    COMPANY, OUTPUT_DIR
)
import operations as ops
ops.init_ops_db()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024


@app.errorhandler(500)
def internal_error(e):
    import traceback
    tb = traceback.format_exc()
    # Show error so we can fix (remove after stable)
    return (
        "<h1>WaveTies Error</h1>"
        "<p>Copy this message and send it for support:</p>"
        "<pre style=\"background:#111;color:#0f0;padding:1rem;overflow:auto;font-size:12px;\">"
        + (tb or str(e))
        + "</pre>",
        500,
    )



try:
    from paths_config import DATA_DIR
except Exception:
    DATA_DIR = ROOT / "data"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
USERS_DB = DATA_DIR / "users.db"
SMTP_CONFIG_FILE = DATA_DIR / "smtp_config.json"
# Log where data lives (visible in Render logs)
print(f"[WaveTies] DATA_DIR = {DATA_DIR.resolve()}", flush=True)


# ──────────────────────────────────────────────────────────────
# Users (SQLite + hashed passwords)
# ──────────────────────────────────────────────────────────────
def get_users_db():
    conn = sqlite3.connect(str(USERS_DB))
    conn.row_factory = sqlite3.Row
    return conn


# Role catalogue (value stored in DB → display label)
ROLES = [
    ("receptionist", "Receptionist"),
    ("operations", "Operations"),
    ("accountant", "Accountant"),
    ("manager", "Manager"),
    ("admin", "Admin"),
]
ROLE_LABELS = dict(ROLES)
# Legacy alias: old "worker" accounts behave like receptionist
ROLE_ALIASES = {"worker": "receptionist"}

# Permission sets
ADMIN_ROLES = {"admin"}
MANAGE_ROLES = {"admin", "manager"}           # edit / delete commercial records
FINANCE_ROLES = {"admin", "manager", "accountant"}  # mark paid, payments, accounts view
OPS_STATUS_ROLES = {"admin", "manager", "operations"}  # update order/shipment status
CREATE_ROLES = {"admin", "manager", "accountant", "operations", "receptionist", "worker"}

PERMISSIONS = [
    ("dashboard", "Dashboard"),
    ("invoices_view", "View invoices"),
    ("invoices_create", "Create invoices"),
    ("invoices_edit", "Edit / delete invoices"),
    ("invoices_pay", "Record invoice payments"),
    ("customers", "Customers (invoice contacts)"),
    ("clients_view", "View clients"),
    ("clients_manage", "Add / edit / delete clients"),
    ("orders_view", "View orders"),
    ("orders_manage", "Create / edit / delete orders"),
    ("orders_status", "Update order & shipment status"),
    ("payments", "Ops payments register"),
    ("expenses", "Expenses"),
    ("incomes", "Income"),
    ("shipments", "Shipments"),
    ("rmb", "RMB desk"),
    ("sourcing", "Sourcing"),
    ("reports", "Reports"),
    ("financial", "Financial report & PDF"),
    ("accounts", "Accounts / treasury"),
    ("users", "Manage users & permissions"),
    ("smtp", "Email / SMTP settings"),
    ("reset_data", "Reset system data"),
]
PERM_KEYS = [p[0] for p in PERMISSIONS]
PERM_LABELS = dict(PERMISSIONS)
ROLE_DEFAULT_PERMISSIONS = {
    "admin": list(PERM_KEYS),
    "manager": [
        "dashboard", "invoices_view", "invoices_create", "invoices_edit", "invoices_pay",
        "customers", "clients_view", "clients_manage", "orders_view", "orders_manage",
        "orders_status", "payments", "expenses", "incomes", "shipments", "rmb", "sourcing",
        "reports", "financial", "accounts",
    ],
    "accountant": [
        "dashboard", "invoices_view", "invoices_create", "invoices_pay", "customers",
        "clients_view", "orders_view", "payments", "expenses", "incomes",
        "reports", "financial", "accounts",
    ],
    "operations": [
        "dashboard", "invoices_view", "clients_view", "orders_view", "orders_manage",
        "orders_status", "shipments", "rmb", "sourcing",
    ],
    "receptionist": [
        "dashboard", "invoices_view", "invoices_create", "customers",
        "clients_view", "orders_view", "orders_manage",
    ],
}


def parse_permissions(raw):
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    s = str(raw).strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            import json as _json
            data = _json.loads(s)
            if isinstance(data, list):
                return [str(x) for x in data]
        except Exception:
            pass
    return [x.strip() for x in s.split(",") if x.strip()]


def permissions_for_role(role):
    r = normalize_role(role)
    if r == "admin":
        return list(PERM_KEYS)
    return list(ROLE_DEFAULT_PERMISSIONS.get(r, ROLE_DEFAULT_PERMISSIONS["receptionist"]))


def has_perm(perm):
    try:
        if not session.get("username"):
            return False
        if normalize_role(session.get("role")) == "admin":
            return True
        perms = session.get("permissions") or []
        if isinstance(perms, str):
            perms = parse_permissions(perms)
        return perm in perms
    except Exception:
        return False




def form_order_id():
    """Prefer manual Order ID if typed, else dropdown selection."""
    manual = (request.form.get("order_id_manual") or "").strip()
    selected = (request.form.get("order_id") or "").strip()
    return manual or selected

def normalize_role(role):
    r = (role or "receptionist").strip().lower()
    return ROLE_ALIASES.get(r, r)


def role_label(role):
    r = normalize_role(role)
    return ROLE_LABELS.get(r, r.title())


def user_can(session_or_role, *allowed):
    """Check if current role is in the allowed set (after alias normalize)."""
    if isinstance(session_or_role, dict):
        role = session_or_role.get("role")
    else:
        role = session_or_role
    return normalize_role(role) in {normalize_role(a) for a in allowed}


def init_users_db():
    conn = get_users_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'receptionist',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT
        )
    """)
    conn.commit()
    # Migrate legacy "worker" → "receptionist"
    try:
        conn.execute("UPDATE users SET role='receptionist' WHERE role='worker'")
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
            if "permissions" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN permissions TEXT DEFAULT ''")
        except Exception:
            pass
        conn.commit()
    except Exception:
        pass
    # Seed users ONLY when the table is empty (never overwrites existing accounts).
    # Demo accounts only if SEED_DEMO_USERS=1. Otherwise a single admin from env.
    cur = conn.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        seed_demo = (os.environ.get("SEED_DEMO_USERS") or "").strip() in ("1", "true", "yes")
        if seed_demo:
            defaults = [
                ("admin", os.environ.get("ADMIN_PASSWORD") or "admin123", "System Admin", "admin"),
                ("manager", "manager123", "Operations Manager", "manager"),
                ("accountant", "account123", "Accounts Officer", "accountant"),
                ("ops", "ops123", "Operations Officer", "operations"),
                ("reception", "reception123", "Front Desk", "receptionist"),
            ]
        else:
            # Production-safe: one admin only (change password after first login)
            admin_user = (os.environ.get("ADMIN_USERNAME") or "admin").strip().lower()
            admin_pass = os.environ.get("ADMIN_PASSWORD") or "admin123"
            defaults = [
                (admin_user, admin_pass, "System Admin", "admin"),
            ]
        for u, p, n, r in defaults:
            conn.execute(
                "INSERT INTO users (username, password_hash, name, role, created_at) VALUES (?,?,?,?,?)",
                (u, generate_password_hash(p), n, r, datetime.now().isoformat(timespec="seconds"))
            )
        conn.commit()
        print(f"[WaveTies] Seeded {len(defaults)} user(s) into empty database.", flush=True)
    else:
        print(f"[WaveTies] Users DB has existing accounts — seed skipped.", flush=True)
    conn.close()


def get_user(username):
    conn = get_users_db()
    row = conn.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_users():
    conn = get_users_db()
    rows = conn.execute("SELECT * FROM users ORDER BY username").fetchall()
    conn.close()
    return [dict(r) for r in rows]


init_users_db()


# ──────────────────────────────────────────────────────────────
# Auth decorators
# ──────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Strict Admin only (Users, SMTP, Reset Data)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if normalize_role(session.get("role")) not in ADMIN_ROLES:
            flash("Admin access required.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


def manage_required(f):
    """Admin/Manager or granular manage permissions."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if normalize_role(session.get("role")) in MANAGE_ROLES:
            return f(*args, **kwargs)
        if any(has_perm(p) for p in ("invoices_edit", "clients_manage", "orders_manage")):
            return f(*args, **kwargs)
        flash("Manager or Admin access required.", "danger")
        return redirect(url_for("dashboard"))
    return decorated


def finance_required(f):
    """Finance roles or granular finance permissions."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if normalize_role(session.get("role")) in FINANCE_ROLES:
            return f(*args, **kwargs)
        if any(has_perm(p) for p in ("invoices_pay", "expenses", "incomes", "accounts", "payments", "financial")):
            return f(*args, **kwargs)
        flash("Finance access required.", "danger")
        return redirect(url_for("dashboard"))
    return decorated


def ops_status_required(f):
    """Ops roles or orders_status permission."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if normalize_role(session.get("role")) in OPS_STATUS_ROLES:
            return f(*args, **kwargs)
        if has_perm("orders_status"):
            return f(*args, **kwargs)
        flash("Operations access required.", "danger")
        return redirect(url_for("dashboard"))
    return decorated


# ──────────────────────────────────────────────────────────────
# Auth routes
# ──────────────────────────────────────────────────────────────
@app.context_processor
def inject_perms():
    try:
        return {"has_perm": has_perm, "PERM_LABELS": PERM_LABELS}
    except Exception:
        return {"has_perm": lambda *_: False, "PERM_LABELS": {}}

@app.route("/")
def index():
    if "username" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = get_user(username)
        if user and check_password_hash(user["password_hash"], password):
            session["username"] = user["username"]
            session["role"] = normalize_role(user["role"])
            raw_perms = user.get("permissions") if isinstance(user, dict) else None
            perms = parse_permissions(raw_perms)
            if not perms:
                perms = permissions_for_role(user.get("role") if isinstance(user, dict) else "receptionist")
            session["permissions"] = perms
            session["name"] = user["name"]
            flash(f"Welcome back, {user['name']}!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html", company=COMPANY)


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# ── Password reset tokens (JSON) ──────────────────────────────
RESET_TOKENS_FILE = DATA_DIR / "reset_tokens.json"
# Emergency recovery key — set WAVETIES_RECOVERY_KEY on Render for production
DEFAULT_RECOVERY_KEY = "WaveTies-Recover-2026"


def _load_reset_tokens():
    if RESET_TOKENS_FILE.exists():
        try:
            with open(RESET_TOKENS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_reset_tokens(data):
    with open(RESET_TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _create_reset_token(username, hours=2):
    token = secrets.token_urlsafe(32)
    tokens = _load_reset_tokens()
    # drop expired
    now = datetime.now()
    tokens = {
        k: v for k, v in tokens.items()
        if v.get("expires") and datetime.fromisoformat(v["expires"]) > now
    }
    tokens[token] = {
        "username": username,
        "expires": (now + timedelta(hours=hours)).isoformat(timespec="seconds"),
        "created": now.isoformat(timespec="seconds"),
    }
    _save_reset_tokens(tokens)
    return token


def _consume_reset_token(token):
    tokens = _load_reset_tokens()
    entry = tokens.pop(token, None)
    _save_reset_tokens(tokens)
    if not entry:
        return None
    try:
        if datetime.fromisoformat(entry["expires"]) < datetime.now():
            return None
    except Exception:
        return None
    return entry.get("username")


def _set_user_password(username, new_password):
    conn = get_users_db()
    row = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute(
        "UPDATE users SET password_hash=? WHERE username=?",
        (generate_password_hash(new_password), username),
    )
    conn.commit()
    conn.close()
    return True


def _send_reset_email(to_email, username, reset_url):
    smtp = load_smtp_config()
    if not smtp.get("host") or not smtp.get("user") or not smtp.get("password"):
        return False, "Email is not configured."
    try:
        msg = MIMEMultipart()
        msg["Subject"] = "WaveTies – Password reset"
        msg["From"] = smtp.get("from_email") or smtp["user"]
        msg["To"] = to_email
        body = (
            f"Hello {username},\n\n"
            f"A password reset was requested for your WaveTies account.\n\n"
            f"Open this link within 2 hours to set a new password:\n{reset_url}\n\n"
            f"If you did not request this, ignore this email.\n\n"
            f"— WaveTies"
        )
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(smtp["host"], int(smtp.get("port", 587))) as server:
            if smtp.get("use_tls", True):
                server.starttls()
            server.login(smtp["user"], smtp["password"])
            server.send_message(msg)
        return True, "ok"
    except Exception as e:
        return False, str(e)


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        # Always respond generically to avoid user enumeration
        user = None
        conn = get_users_db()
        row = conn.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
        conn.close()
        if row:
            user = dict(row)
        if user:
            token = _create_reset_token(user["username"])
            reset_url = url_for("reset_password", token=token, _external=True)
            # Prefer company/user email if present — users table may not have email; try SMTP notify admin path
            smtp = load_smtp_config()
            to_addr = smtp.get("from_email") or smtp.get("user") or ""
            # If the account is admin and we have SMTP, send there so admin can recover
            if to_addr and smtp.get("host"):
                ok, err = _send_reset_email(to_addr, user["username"], reset_url)
                if ok:
                    flash(
                        "If that account exists and email is configured, a reset link was sent to the system mailbox. "
                        "Also check Admin recovery if you are locked out.",
                        "success",
                    )
                else:
                    flash(
                        f"Could not send email ({err}). Use Admin recovery with your recovery key instead.",
                        "warning",
                    )
            else:
                # No SMTP — guide to recovery page; still create token for manual use by support
                flash(
                    "Email is not configured. Use Admin recovery (recovery key) to reset the admin password, "
                    "or ask another admin to reset your password from Users & Roles.",
                    "warning",
                )
                return redirect(url_for("admin_recovery"))
        else:
            flash(
                "If that account exists, follow the instructions sent or use Admin recovery.",
                "info",
            )
        return redirect(url_for("login"))
    return render_template("forgot_password.html", company=COMPANY)


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    tokens = _load_reset_tokens()
    entry = tokens.get(token)
    username = None
    if entry:
        try:
            if datetime.fromisoformat(entry["expires"]) >= datetime.now():
                username = entry.get("username")
        except Exception:
            username = None
    if not username:
        flash("This reset link is invalid or has expired.", "danger")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        pw = request.form.get("password", "")
        pw2 = request.form.get("password2", "")
        if len(pw) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return redirect(url_for("reset_password", token=token))
        if pw != pw2:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("reset_password", token=token))
        # consume token
        _consume_reset_token(token)
        if _set_user_password(username, pw):
            flash(f"Password updated for {username}. You can sign in now.", "success")
            return redirect(url_for("login"))
        flash("User not found.", "danger")
        return redirect(url_for("login"))

    return render_template("reset_password.html", company=COMPANY, username=username, token=token)


@app.route("/admin-recovery", methods=["GET", "POST"])
def admin_recovery():
    """Emergency admin password reset using recovery key (no login required)."""
    if request.method == "POST":
        key = request.form.get("recovery_key", "")
        username = request.form.get("username", "admin").strip().lower() or "admin"
        pw = request.form.get("password", "")
        pw2 = request.form.get("password2", "")
        expected = os.environ.get("WAVETIES_RECOVERY_KEY", DEFAULT_RECOVERY_KEY)
        if not secrets.compare_digest(key, expected):
            flash("Invalid recovery key.", "danger")
            return redirect(url_for("admin_recovery"))
        if len(pw) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return redirect(url_for("admin_recovery"))
        if pw != pw2:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("admin_recovery"))
        # Only allow resetting accounts that are admin role (or username admin)
        conn = get_users_db()
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()
        if not row:
            flash(f"User '{username}' not found.", "danger")
            return redirect(url_for("admin_recovery"))
        user = dict(row)
        if normalize_role(user.get("role")) != "admin" and username != "admin":
            flash("Recovery only works for admin accounts.", "danger")
            return redirect(url_for("admin_recovery"))
        if _set_user_password(username, pw):
            flash(f"Password for '{username}' has been reset. Sign in with the new password.", "success")
            return redirect(url_for("login"))
        flash("Could not update password.", "danger")
        return redirect(url_for("admin_recovery"))
    return render_template("admin_recovery.html", company=COMPANY)


# ──────────────────────────────────────────────────────────────
# Dashboard & Reports
# ──────────────────────────────────────────────────────────────
@app.route("/dashboard")
@login_required
def dashboard():
    db = load_db()
    invoices = db.get("invoices", {})
    sorted_invs = sorted(invoices.items(), key=lambda x: x[1].get("created_at", ""), reverse=True)

    total_amount = sum(i.get("total", 0) for i in invoices.values())
    outstanding = sum(i.get("balance_due", 0) for i in invoices.values() if i.get("balance_due", 0) > 0)
    paid_count = sum(1 for i in invoices.values() if i.get("balance_due", 0) <= 0)
    due_count = sum(1 for i in invoices.values() if i.get("balance_due", 0) > 0)

    stats = {
        "total": len(invoices),
        "due": due_count,
        "paid": paid_count,
        "total_amount": total_amount,
        "outstanding": outstanding,
    }
    try:
        ops_stats = ops.ops_kpis()
    except Exception:
        ops_stats = {
            "active_orders": 0, "pending_pay": 0, "in_transit": 0,
            "total_rev": 0, "active_clients": 0,
        }
    month = datetime.now().strftime("%Y-%m")
    try:
        exp_summary = ops.expense_summary(month)
    except Exception:
        exp_summary = {"total_usd": 0, "paid_usd": 0, "pending_usd": 0, "by_category": []}
    try:
        inc_summary = ops.income_summary(month)
        pnl = ops.pnl_summary(month)
    except Exception:
        inc_summary = {"total_usd": 0, "received_usd": 0, "pending_usd": 0, "by_category": []}
        pnl = {"income_usd": 0, "expense_usd": 0, "net_usd": 0}
    # Fix any GHS/USD 1:1 mistakes using live FX rates (idempotent)
    try:
        ops.recalc_usd_amounts()
    except Exception as _fx:
        print(f"[WaveTies] FX recalc: {_fx}", flush=True)
    # Always derive wallets from linked expenses / incomes / invoice payments
    try:
        wallets, _ne, _ni, _np = rebuild_wallet_balances()
    except Exception:
        try:
            wallets = (load_receiving_accounts() or {}).get("wallets") or {}
        except Exception:
            wallets = {}
    try:
        recent_orders = ops.order_list()[:8]
    except Exception:
        recent_orders = []
    return render_template(
        "dashboard.html",
        invoices=sorted_invs[:15],
        stats=stats,
        ops_stats=ops_stats,
        recent_orders=recent_orders,
        exp_summary=exp_summary,
        inc_summary=inc_summary,
        pnl=pnl,
        exp_month=month,
        wallets=wallets,
        fx_rates=ops.get_fx_rates(),
        fx_as_of=ops.get_fx_as_of(),
        company=COMPANY,
        user=session,
    )


@app.route("/reports")
@login_required
def reports():
    db = load_db()
    invoices = db.get("invoices", {})

    # By month
    by_month = defaultdict(lambda: {"count": 0, "total": 0.0, "paid": 0.0, "outstanding": 0.0})
    by_worker = defaultdict(lambda: {"count": 0, "total": 0.0})
    by_transport = defaultdict(lambda: {"count": 0, "total": 0.0})

    for inv in invoices.values():
        created = inv.get("created_at") or inv.get("invoice_date") or ""
        month = created[:7] if len(created) >= 7 else "Unknown"
        by_month[month]["count"] += 1
        by_month[month]["total"] += inv.get("total", 0)
        by_month[month]["paid"] += inv.get("paid", 0)
        by_month[month]["outstanding"] += max(0, inv.get("balance_due", 0))

        worker = inv.get("created_by") or "unknown"
        by_worker[worker]["count"] += 1
        by_worker[worker]["total"] += inv.get("total", 0)

        for item in inv.get("items") or []:
            t = item.get("transport") or "OTHER"
            by_transport[t]["count"] += 1
            by_transport[t]["total"] += item.get("amount", 0)

    months = sorted(by_month.keys(), reverse=True)
    try:
        exp_all = ops.expense_summary()
        exp_month = ops.expense_summary(datetime.now().strftime("%Y-%m"))
        inc_all = ops.income_summary()
        inc_month = ops.income_summary(datetime.now().strftime("%Y-%m"))
        pnl = ops.pnl_summary(datetime.now().strftime("%Y-%m"))
    except Exception:
        exp_all = {"total_usd": 0, "by_category": []}
        exp_month = exp_all
        inc_all = exp_all
        inc_month = exp_all
        pnl = {"income_usd": 0, "expense_usd": 0, "net_usd": 0}
    return render_template(
        "reports.html",
        by_month=[(m, by_month[m]) for m in months],
        by_worker=sorted(by_worker.items(), key=lambda x: -x[1]["total"]),
        by_transport=sorted(by_transport.items(), key=lambda x: -x[1]["total"]),
        exp_all=exp_all,
        exp_month=exp_month,
        inc_all=inc_all,
        inc_month=inc_month,
        pnl=pnl,
        company=COMPANY,
        user=session,
    )


# ──────────────────────────────────────────────────────────────
# Invoices
# ──────────────────────────────────────────────────────────────
@app.route("/invoices")
@login_required
def invoice_list():
    db = load_db()
    invoices = db.get("invoices", {})
    status_filter = request.args.get("status", "all")
    sorted_invs = sorted(invoices.items(), key=lambda x: x[1].get("created_at", ""), reverse=True)
    if status_filter == "due":
        sorted_invs = [(n, i) for n, i in sorted_invs if i.get("balance_due", 0) > 0]
    elif status_filter == "paid":
        sorted_invs = [(n, i) for n, i in sorted_invs if i.get("balance_due", 0) <= 0]
    return render_template(
        "invoices.html",
        invoices=sorted_invs,
        status_filter=status_filter,
        company=COMPANY,
        user=session,
    )


@app.route("/invoices/new", methods=["GET", "POST"])
@login_required
def create_invoice_page():
    db = load_db()
    customers = list(db.get("customers", {}).values())

    if request.method == "POST":
        try:
            customer_name = request.form.get("customer_name", "").strip()
            customer_email = request.form.get("customer_email", "").strip()
            customer_phone = request.form.get("customer_phone", "").strip()
            currency = request.form.get("currency", "USD")
            tax = float(request.form.get("tax", 0) or 0)
            paid = float(request.form.get("paid", 0) or 0)
            due_days = int(request.form.get("due_days", 30) or 30)

            trackings = request.form.getlist("tracking[]")
            item_names = request.form.getlist("item_name[]")
            transports = request.form.getlist("transport[]")
            boxes_list = request.form.getlist("boxes[]")
            weights = request.form.getlist("weight_kg[]")
            vols = request.form.getlist("vol_cbm[]")
            order_nos = request.form.getlist("order_number[]")
            amounts = request.form.getlist("amount[]")

            items = []
            for i in range(len(trackings)):
                if not trackings[i].strip():
                    continue
                items.append({
                    "tracking": trackings[i].strip(),
                    "item_name": item_names[i].strip() if i < len(item_names) else "Goods",
                    "transport": transports[i].strip() if i < len(transports) else "SEA_FREIGHT",
                    "boxes": int(boxes_list[i] or 1) if i < len(boxes_list) else 1,
                    "weight_kg": float(weights[i] or 0) if i < len(weights) else 0,
                    "vol_cbm": float(vols[i] or 0) if i < len(vols) else 0,
                    "order_number": order_nos[i].strip() if i < len(order_nos) else "",
                    "amount": float(amounts[i] or 0) if i < len(amounts) else 0,
                })

            if not customer_name:
                flash("Customer name is required.", "danger")
                return redirect(url_for("create_invoice_page"))
            if not items:
                flash("At least one line item is required.", "danger")
                return redirect(url_for("create_invoice_page"))

            inv_date = datetime.now()
            due_date = inv_date + timedelta(days=due_days)
            ra = load_receiving_accounts()
            momo_provider = (request.form.get("momo_provider") or "").strip()
            if not momo_provider:
                momo_provider = ra.get("momo_provider") or "TELECEL CASH"
            momo_val = (request.form.get("momo") or "").strip() or ra.get("momo") or COMPANY.get("momo", "")
            bank_src = request.form.get("bank_details")
            if bank_src is None or not str(bank_src).strip():
                bank_src = "\n".join(ra.get("bank_lines") or COMPANY.get("bank_lines", []))
            currency = (currency or "USD").strip().upper()
            data = {
                "customer_name": customer_name,
                "customer_email": customer_email,
                "customer_phone": customer_phone,
                "invoice_date": inv_date.strftime("%b %d, %Y"),
                "due_date": due_date.strftime("%b %d, %Y"),
                "currency": currency,
                "tax": tax,
                "paid": paid,
                "items": items,
                "momo": momo_val,
                "momo_provider": momo_provider,
                "bank_lines": [
                    line.strip()
                    for line in str(bank_src).splitlines()
                    if line.strip()
                ],
                "contact_phone": (request.form.get("contact_phone") or "").strip() or ra.get("contact_phone") or COMPANY.get("phone"),
            }
            inv_no = create_invoice(data, created_by=session.get("username", "worker"))
            flash(f"Invoice {inv_no} created successfully!", "success")
            return redirect(url_for("view_invoice", invoice_no=inv_no))
        except Exception as e:
            flash(f"Error creating invoice: {e}", "danger")
            return redirect(url_for("create_invoice_page"))

    ra = load_receiving_accounts()
    return render_template(
        "create_invoice.html",
        company=COMPANY,
        user=session,
        customers=customers,
        default_momo=ra.get("momo") or COMPANY.get("momo", ""),
        default_bank="\n".join(ra.get("bank_lines") or COMPANY.get("bank_lines", [])),
        default_phone=ra.get("contact_phone") or COMPANY.get("phone", ""),
        default_momo_provider=ra.get("momo_provider") or "TELECEL CASH",
        currencies=CURRENCIES,
        default_currency=ra.get("preferred_currency") or "USD",
    )


@app.route("/invoices/<path:invoice_no>")
@login_required
def view_invoice(invoice_no):
    db = load_db()
    inv = db["invoices"].get(invoice_no)
    if not inv:
        flash("Invoice not found.", "danger")
        return redirect(url_for("invoice_list"))
    return render_template(
        "view_invoice.html",
        inv=inv,
        invoice_no=invoice_no,
        company=COMPANY,
        user=session,
    )


@app.route("/invoices/<path:invoice_no>/edit", methods=["GET", "POST"])
@login_required
@manage_required
def edit_invoice(invoice_no):
    """Admin/Manager: edit invoice header, lines, payments, and receiving details."""
    db = load_db()
    inv = db.get("invoices", {}).get(invoice_no)
    if not inv:
        flash("Invoice not found.", "danger")
        return redirect(url_for("invoice_list"))

    if request.method == "POST":
        try:
            customer_name = request.form.get("customer_name", "").strip()
            if not customer_name:
                flash("Customer name is required.", "danger")
                return redirect(url_for("edit_invoice", invoice_no=invoice_no))

            trackings = request.form.getlist("tracking[]")
            item_names = request.form.getlist("item_name[]")
            transports = request.form.getlist("transport[]")
            boxes_list = request.form.getlist("boxes[]")
            weights = request.form.getlist("weight_kg[]")
            vols = request.form.getlist("vol_cbm[]")
            order_nos = request.form.getlist("order_number[]")
            amounts = request.form.getlist("amount[]")

            items = []
            for i in range(len(trackings)):
                if not (trackings[i] or "").strip() and not (amounts[i] if i < len(amounts) else ""):
                    continue
                if not (trackings[i] or "").strip():
                    continue
                items.append({
                    "tracking": trackings[i].strip(),
                    "item_name": item_names[i].strip() if i < len(item_names) else "Goods",
                    "transport": transports[i].strip() if i < len(transports) else "SEA_FREIGHT",
                    "boxes": int(float(boxes_list[i] or 1)) if i < len(boxes_list) else 1,
                    "weight_kg": float(weights[i] or 0) if i < len(weights) else 0,
                    "vol_cbm": float(vols[i] or 0) if i < len(vols) else 0,
                    "order_number": order_nos[i].strip() if i < len(order_nos) else "",
                    "amount": float(amounts[i] or 0) if i < len(amounts) else 0,
                })
            if not items:
                flash("At least one line item is required.", "danger")
                return redirect(url_for("edit_invoice", invoice_no=invoice_no))

            tax = float(request.form.get("tax", 0) or 0)
            paid = float(request.form.get("paid", 0) or 0)
            subtotal = round(sum(it["amount"] for it in items), 2)
            total = round(subtotal + tax, 2)
            balance_due = round(max(0, total - paid), 2)
            currency = (request.form.get("currency") or inv.get("currency") or "USD").strip().upper()

            inv["customer_name"] = customer_name
            inv["customer_email"] = request.form.get("customer_email", "").strip()
            inv["customer_phone"] = request.form.get("customer_phone", "").strip()
            inv["currency"] = currency
            inv["invoice_date"] = request.form.get("invoice_date") or inv.get("invoice_date")
            inv["due_date"] = request.form.get("due_date") or inv.get("due_date")
            inv["items"] = items
            inv["subtotal"] = subtotal
            inv["tax"] = tax
            inv["total"] = total
            inv["paid"] = paid
            inv["balance_due"] = balance_due
            inv["momo_provider"] = (request.form.get("momo_provider") or inv.get("momo_provider") or "TELECEL CASH").strip()
            inv["momo"] = (request.form.get("momo") or "").strip()
            inv["bank_lines"] = [
                ln.strip()
                for ln in (request.form.get("bank_details") or "").splitlines()
                if ln.strip()
            ]
            inv["contact_phone"] = (request.form.get("contact_phone") or "").strip()
            inv["notes"] = (request.form.get("notes") or "").strip()
            inv["updated_at"] = datetime.now().isoformat(timespec="seconds")
            inv["updated_by"] = session.get("username") or session.get("name")

            db["invoices"][invoice_no] = inv
            save_db(db)

            # Force PDF rebuild
            safe_name = invoice_no.replace("/", "-")
            pdf_path = OUTPUT_DIR / f"Invoice_{safe_name}.pdf"
            try:
                generate_invoice(inv, str(pdf_path))
            except Exception:
                pass

            flash(f"Invoice {invoice_no} updated.", "success")
            return redirect(url_for("view_invoice", invoice_no=invoice_no))
        except Exception as e:
            flash(f"Could not update invoice: {e}", "danger")
            return redirect(url_for("edit_invoice", invoice_no=invoice_no))

    # Normalize so older invoices cannot crash the edit form
    bank_lines = inv.get("bank_lines") or []
    if isinstance(bank_lines, str):
        bank_lines = [ln.strip() for ln in bank_lines.splitlines() if ln.strip()]
    elif not isinstance(bank_lines, (list, tuple)):
        bank_lines = []
    bank_text = "\n".join(str(x) for x in bank_lines)

    raw_items = inv.get("items") or []
    norm_items = []
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        norm_items.append({
            "tracking": it.get("tracking") or it.get("tracking_no") or it.get("tracking_number") or "",
            "item_name": it.get("item_name") or it.get("description") or it.get("name") or "Goods",
            "transport": it.get("transport") or "SEA_FREIGHT",
            "boxes": it.get("boxes") or 1,
            "weight_kg": it.get("weight_kg") or it.get("weight") or 0,
            "vol_cbm": it.get("vol_cbm") or it.get("volume") or 0,
            "order_number": it.get("order_number") or it.get("order_no") or it.get("order_id") or "",
            "amount": it.get("amount") or 0,
        })
    inv_view = dict(inv)
    inv_view["items"] = norm_items

    currency_list = list(CURRENCIES) if CURRENCIES else ["USD", "GHS", "EUR", "GBP", "CNY"]
    try:
        return render_template(
            "edit_invoice.html",
            inv=inv_view,
            invoice_no=invoice_no,
            bank_text=bank_text,
            company=COMPANY,
            user=session,
            currencies=currency_list,
            providers=["TELECEL CASH", "MTN MOMO", "AT MONEY", "OTHER"],
        )
    except Exception as e:
        flash(f"Could not open edit form: {e}", "danger")
        return redirect(url_for("view_invoice", invoice_no=invoice_no))


@app.route("/invoices/<path:invoice_no>/pdf")
@login_required
def download_pdf(invoice_no):
    db = load_db()
    inv = db["invoices"].get(invoice_no)
    if not inv:
        flash("Invoice not found.", "danger")
        return redirect(url_for("invoice_list"))
    safe_name = invoice_no.replace("/", "-")
    pdf_path = OUTPUT_DIR / f"Invoice_{safe_name}.pdf"
    # Always regenerate so logo/branding updates apply immediately
    generate_invoice(inv, str(pdf_path))
    return send_file(pdf_path, as_attachment=True, download_name=f"Invoice_{safe_name}.pdf", mimetype="application/pdf")



@app.route("/invoices/<path:invoice_no>/receipt/<receipt_no>")
@login_required
def download_receipt(invoice_no, receipt_no):
    """Download official payment receipt PDF."""
    db = load_db()
    inv = db.get("invoices", {}).get(invoice_no)
    if not inv:
        flash("Invoice not found.", "danger")
        return redirect(url_for("dashboard"))
    safe = receipt_no.replace("/", "-")
    pdf_path = OUTPUT_DIR / f"Receipt_{safe}.pdf"
    if not pdf_path.exists():
        # try regenerate from stored receipt data or payment
        try:
            rdata = (db.get("receipts") or {}).get(receipt_no)
            if rdata:
                generate_receipt(rdata, str(pdf_path))
            else:
                # find payment with this receipt_no
                for p in inv.get("payments") or []:
                    if p.get("receipt_no") == receipt_no:
                        create_receipt_for_payment(inv, p, invoice_no)
                        break
        except Exception as e:
            flash(f"Receipt not available: {e}", "danger")
            return redirect(url_for("view_invoice", invoice_no=invoice_no))
    if not pdf_path.exists():
        flash("Receipt PDF not found.", "danger")
        return redirect(url_for("view_invoice", invoice_no=invoice_no))
    from flask import send_file
    return send_file(pdf_path, as_attachment=True, download_name=f"Receipt_{safe}.pdf")


@app.route("/invoices/<path:invoice_no>/receipts/latest")
@login_required
def download_latest_receipt(invoice_no):
    db = load_db()
    inv = db.get("invoices", {}).get(invoice_no)
    if not inv:
        flash("Invoice not found.", "danger")
        return redirect(url_for("dashboard"))
    receipt_no = None
    for p in reversed(inv.get("payments") or []):
        if p.get("receipt_no"):
            receipt_no = p["receipt_no"]
            break
    if not receipt_no:
        flash("No receipt for this invoice yet. Record a payment first.", "warning")
        return redirect(url_for("view_invoice", invoice_no=invoice_no))
    return redirect(url_for("download_receipt", invoice_no=invoice_no, receipt_no=receipt_no))


@app.route("/invoices/<path:invoice_no>/regenerate")
@login_required
def regenerate_pdf(invoice_no):
    db = load_db()
    inv = db["invoices"].get(invoice_no)
    if not inv:
        flash("Invoice not found.", "danger")
        return redirect(url_for("invoice_list"))
    safe_name = invoice_no.replace("/", "-")
    pdf_path = OUTPUT_DIR / f"Invoice_{safe_name}.pdf"
    generate_invoice(inv, str(pdf_path))
    flash("PDF regenerated.", "success")
    return redirect(url_for("view_invoice", invoice_no=invoice_no))



@app.route("/invoices/<path:invoice_no>/delete", methods=["POST"])
@login_required
@manage_required
def delete_invoice(invoice_no):
    db = load_db()
    inv = db.get("invoices", {}).pop(invoice_no, None)
    if not inv:
        flash("Invoice not found.", "danger")
        return redirect(url_for("invoice_list"))
    save_db(db)

    # Undo payment effects ONCE: reverse wallet credits, remove linked income rows.
    # Do not reverse wallet again when deleting income (would double-subtract).
    reversed_wallets = 0
    removed_incomes = 0
    linked_income_ids = set()
    try:
        for pay in (inv.get("payments") or []):
            acc = (pay.get("account") or "").strip()
            try:
                amt = float(pay.get("amount") or 0)
            except Exception:
                amt = 0.0
            if acc and amt:
                adjust_wallet(acc, -amt, pay.get("currency") or inv.get("currency"))
                reversed_wallets += 1
            iid = (pay.get("income_id") or "").strip()
            if iid:
                linked_income_ids.add(iid)

        # Remove income rows for this invoice (by id or reference) — wallet already fixed above
        try:
            for inc in ops.list_incomes(limit=2000):
                iid = (inc.get("income_id") or "").strip()
                if not iid:
                    continue
                tied = (
                    iid in linked_income_ids
                    or (inc.get("reference") or "") == invoice_no
                    or (inc.get("subcategory") or "") == invoice_no
                )
                if not tied:
                    continue
                # If this income was NOT from a payment we already reversed, undo its wallet effect once
                if iid not in linked_income_ids:
                    a, d = wallet_effect_income(inc)
                    if a and d:
                        adjust_wallet(a, -d, inc.get("currency"))
                        reversed_wallets += 1
                try:
                    ops.delete("incomes", "income_id", iid)
                    removed_incomes += 1
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        pass

    # Remove PDF if present
    safe_name = invoice_no.replace("/", "-")
    pdf_path = OUTPUT_DIR / f"Invoice_{safe_name}.pdf"
    try:
        if pdf_path.exists():
            pdf_path.unlink()
    except Exception:
        pass
    # Unlink from orders
    try:
        for o in ops.order_list():
            if o.get("invoice_no") == invoice_no:
                ops.update("orders", "order_id", o["order_id"], {"invoice_no": ""})
    except Exception:
        pass

    extra = []
    if reversed_wallets:
        extra.append(f"{reversed_wallets} account adjustment(s)")
    if removed_incomes:
        extra.append(f"{removed_incomes} income record(s) removed")
    msg = f"Invoice {invoice_no} deleted."
    if extra:
        msg += " " + "; ".join(extra) + "."
    flash(msg, "success")
    return redirect(url_for("invoice_list"))


# ── Mark as Paid ──────────────────────────────────────────────
@app.route("/invoices/<path:invoice_no>/pay", methods=["GET", "POST"])
@login_required
@finance_required
def mark_paid(invoice_no):
    db = load_db()
    inv = db["invoices"].get(invoice_no)
    if not inv:
        flash("Invoice not found.", "danger")
        return redirect(url_for("invoice_list"))

    if request.method == "POST":
        try:
            amount = float(request.form.get("amount", 0) or 0)
            note = request.form.get("note", "").strip()
            account = (request.form.get("account") or "").strip()
            method = (request.form.get("method") or "").strip()
            if amount <= 0:
                flash("Payment amount must be greater than zero.", "danger")
                return redirect(url_for("mark_paid", invoice_no=invoice_no))
            if not account:
                flash("Select where the payment was received (Cash, MoMo, or Bank).", "danger")
                return redirect(url_for("mark_paid", invoice_no=invoice_no))

            inv["paid"] = round(inv.get("paid", 0) + amount, 2)
            inv["balance_due"] = round(max(0, inv.get("total", 0) - inv["paid"]), 2)
            inv.setdefault("payments", [])
            pay_currency = (inv.get("currency") or "GHS").upper()
            payment_entry = {
                "amount": amount,
                "amount_usd": ops.to_usd(amount, pay_currency),
                "note": note,
                "account": account,
                "method": method,
                "currency": pay_currency,
                "fx_rate": ops.get_fx_rates().get(pay_currency),
                "by": session.get("username"),
                "at": datetime.now().isoformat(timespec="seconds"),
            }
            inv["payments"].append(payment_entry)
            db["invoices"][invoice_no] = inv
            save_db(db)

            # Credit selected wallet (Cash / MoMo / Bank)
            adjust_wallet(account, amount, inv.get("currency"))

            # Also record under Income so Financial Report / net includes this payment
            try:
                currency = (inv.get("currency") or "GHS").upper()
                # Convert to USD using live FX rates (GHS payment ≠ same number in USD)
                amount_usd = ops.to_usd(amount, currency)
                rates = ops.get_fx_rates()
                rate_used = rates.get(currency, 1)
                iid = ops.add_income({
                    "income_date": datetime.now().strftime("%Y-%m-%d"),
                    "category": "Invoice Payment",
                    "subcategory": invoice_no,
                    "description": (note or f"Payment on invoice {invoice_no}").strip(),
                    "client_name": inv.get("customer_name") or "",
                    "order_id": "",
                    "amount": amount,
                    "currency": currency,
                    "amount_usd": amount_usd,
                    "payment_method": method or "Other",
                    "reference": invoice_no,
                    "status": "Received",
                    "recorded_by": session.get("name") or session.get("username"),
                    "notes": f"Auto from invoice payment · account={account}",
                    "account": account,
                })
                payment_entry["income_id"] = iid
                # persist income_id on payment line
                inv["payments"][-1] = payment_entry
                db["invoices"][invoice_no] = inv
                save_db(db)
            except Exception as inc_err:
                # Payment already saved; income is secondary
                flash(f"Payment saved, but income entry failed: {inc_err}", "warning")

            # Regenerate invoice PDF with updated paid/balance
            safe_name = invoice_no.replace("/", "-")
            generate_invoice(inv, str(OUTPUT_DIR / f"Invoice_{safe_name}.pdf"))

            # Official payment receipt for the client
            receipt_no = None
            try:
                receipt_no, rpath = create_receipt_for_payment(inv, payment_entry, invoice_no)
                # reload inv with receipt_no on payment
                inv = load_db()["invoices"].get(invoice_no, inv)
            except Exception as rerr:
                print(f"[WaveTies] receipt generate failed: {rerr}", flush=True)

            acc_label = dict(ACCOUNT_OPTIONS).get(account, account)
            usd_note = ""
            try:
                usd_v = ops.to_usd(amount, inv.get("currency") or "GHS")
                if (inv.get("currency") or "").upper() != "USD":
                    usd_note = f" (≈ ${usd_v:,.2f} USD)"
            except Exception:
                pass
            rnote = f" Receipt {receipt_no} ready." if receipt_no else ""
            if inv["balance_due"] <= 0:
                flash(f"Invoice {invoice_no} fully paid. Credited to {acc_label}{usd_note}.{rnote}", "success")
            else:
                flash(
                    f"Payment of {inv.get('currency','GHS')} {amount:.2f}{usd_note} recorded to {acc_label}. "
                    f"Balance due: {inv['balance_due']:.2f}.{rnote}",
                    "success",
                )
            return redirect(url_for("view_invoice", invoice_no=invoice_no))
        except Exception as e:
            flash(f"Error recording payment: {e}", "danger")

    balance = inv.get("balance_due", inv.get("total", 0))
    ra = load_receiving_accounts()
    return render_template(
        "mark_paid.html",
        inv=inv,
        invoice_no=invoice_no,
        balance=balance,
        accounts=ACCOUNT_OPTIONS,
        wallets=ra.get("wallets") or {},
        company=COMPANY,
        user=session,
    )


# ── Email invoice ─────────────────────────────────────────────
def load_smtp_config():
    if SMTP_CONFIG_FILE.exists():
        with open(SMTP_CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_smtp_config(cfg):
    with open(SMTP_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


@app.route("/invoices/<path:invoice_no>/email", methods=["GET", "POST"])
@login_required
def email_invoice(invoice_no):
    db = load_db()
    inv = db["invoices"].get(invoice_no)
    if not inv:
        flash("Invoice not found.", "danger")
        return redirect(url_for("invoice_list"))

    smtp = load_smtp_config()
    if request.method == "POST":
        to_email = request.form.get("to_email", "").strip()
        subject = request.form.get("subject", f"Invoice {invoice_no} – WaveTies").strip()
        body = request.form.get("body", "").strip()
        if not to_email:
            flash("Recipient email is required.", "danger")
            return redirect(url_for("email_invoice", invoice_no=invoice_no))

        if not smtp.get("host") or not smtp.get("user") or not smtp.get("password"):
            flash("Email is not configured. Ask an admin to set SMTP settings.", "warning")
            return redirect(url_for("email_invoice", invoice_no=invoice_no))

        try:
            safe_name = invoice_no.replace("/", "-")
            pdf_path = OUTPUT_DIR / f"Invoice_{safe_name}.pdf"
            generate_invoice(inv, str(pdf_path))

            msg = MIMEMultipart()
            msg["From"] = smtp.get("from_email") or smtp["user"]
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body or f"Please find invoice {invoice_no} attached.\n\nWaveTies Logistics – Stronger Ties", "plain"))

            with open(pdf_path, "rb") as f:
                part = MIMEBase("application", "pdf")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename=Invoice_{safe_name}.pdf")
            msg.attach(part)

            with smtplib.SMTP(smtp["host"], int(smtp.get("port", 587))) as server:
                if smtp.get("use_tls", True):
                    server.starttls()
                server.login(smtp["user"], smtp["password"])
                server.send_message(msg)

            flash(f"Invoice emailed to {to_email}.", "success")
            return redirect(url_for("view_invoice", invoice_no=invoice_no))
        except Exception as e:
            flash(f"Email failed: {e}", "danger")

    default_body = (
        f"Dear {inv.get('customer_name', 'Customer')},\n\n"
        f"Please find attached invoice {invoice_no}.\n"
        f"Amount due: {inv.get('currency','GHS')} {inv.get('balance_due', inv.get('total', 0)):.2f}\n\n"
        f"Payment details are on the invoice.\n\n"
        f"Thank you,\nWaveTies Logistics And Supply Chain Solutions\nStronger Ties"
    )
    return render_template(
        "email_invoice.html",
        inv=inv,
        invoice_no=invoice_no,
        default_to=inv.get("customer_email", ""),
        default_body=default_body,
        smtp_configured=bool(smtp.get("host") and smtp.get("user")),
        company=COMPANY,
        user=session,
    )


# ──────────────────────────────────────────────────────────────
# Customers
# ──────────────────────────────────────────────────────────────
@app.route("/customers")
@login_required
def customers_list():
    db = load_db()
    customers = sorted(db.get("customers", {}).values(), key=lambda c: c.get("name", "").lower())
    return render_template("customers.html", customers=customers, company=COMPANY, user=session)


@app.route("/customers/new", methods=["GET", "POST"])
@login_required
def customer_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        if not name:
            flash("Name is required.", "danger")
            return redirect(url_for("customer_new"))
        db = load_db()
        key = email or name
        db.setdefault("customers", {})[key] = {"name": name, "email": email, "phone": phone}
        save_db(db)
        flash(f"Customer {name} saved.", "success")
        return redirect(url_for("customers_list"))
    return render_template("customer_form.html", customer=None, company=COMPANY, user=session)


@app.route("/customers/<path:key>/edit", methods=["GET", "POST"])
@login_required
@manage_required
def customer_edit(key):
    db = load_db()
    customer = db.get("customers", {}).get(key)
    if not customer:
        flash("Customer not found.", "danger")
        return redirect(url_for("customers_list"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        if not name:
            flash("Name is required.", "danger")
            return redirect(url_for("customer_edit", key=key))
        # Remove old key if email/name changed
        del db["customers"][key]
        new_key = email or name
        db["customers"][new_key] = {"name": name, "email": email, "phone": phone}
        save_db(db)
        flash("Customer updated.", "success")
        return redirect(url_for("customers_list"))
    return render_template("customer_form.html", customer=customer, customer_key=key, company=COMPANY, user=session)


@app.route("/customers/<path:key>/delete", methods=["POST"])
@login_required
@manage_required
def customer_delete(key):
    db = load_db()
    if key in db.get("customers", {}):
        name = db["customers"][key].get("name", key)
        del db["customers"][key]
        save_db(db)
        flash(f"Customer {name} deleted.", "success")
    return redirect(url_for("customers_list"))


# ──────────────────────────────────────────────────────────────
# Admin: Users & SMTP
# ──────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────
# Admin: Receiving Accounts (treasury) — hidden from workers
# ──────────────────────────────────────────────────────────────
RECEIVING_ACCOUNTS_FILE = DATA_DIR / "receiving_accounts.json"
MOMO_PROVIDERS = ["TELECEL CASH", "MTN MOMO", "AT MONEY", "OTHER"]


def load_receiving_accounts():
    defaults = {
        "momo_provider": "TELECEL CASH",
        "momo": COMPANY.get("momo", ""),
        "bank_lines": list(COMPANY.get("bank_lines", [])),
        "contact_phone": COMPANY.get("phone", ""),
        "billing_email": COMPANY.get("email", ""),
        "internal_notes": "",
        "preferred_currency": "USD",
        "wallets": {
            "cash": {"label": "Cash on Hand", "balance": 0.0, "currency": "GHS"},
            "momo": {"label": "Mobile Money", "balance": 0.0, "currency": "GHS"},
            "bank": {"label": "Bank Account", "balance": 0.0, "currency": "GHS"},
        },
    }
    if RECEIVING_ACCOUNTS_FILE.exists():
        try:
            with open(RECEIVING_ACCOUNTS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            defaults.update(data)
        except Exception:
            pass
    if isinstance(defaults.get("bank_lines"), str):
        defaults["bank_lines"] = [ln.strip() for ln in defaults["bank_lines"].splitlines() if ln.strip()]
    # Ensure wallet structure exists
    wallets = defaults.get("wallets") or {}
    for key, label, cur in (
        ("cash", "Cash on Hand", "GHS"),
        ("momo", "Mobile Money", "GHS"),
        ("bank", "Bank Account", "GHS"),
    ):
        if key not in wallets or not isinstance(wallets.get(key), dict):
            wallets[key] = {"label": label, "balance": 0.0, "currency": cur}
        else:
            wallets[key].setdefault("label", label)
            wallets[key].setdefault("balance", 0.0)
            wallets[key].setdefault("currency", cur)
            try:
                wallets[key]["balance"] = float(wallets[key]["balance"] or 0)
            except Exception:
                wallets[key]["balance"] = 0.0
    defaults["wallets"] = wallets
    return defaults


def save_receiving_accounts(data):
    with open(RECEIVING_ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


ACCOUNT_OPTIONS = [
    ("cash", "Cash on Hand"),
    ("momo", "Mobile Money"),
    ("bank", "Bank Account"),
]


def adjust_wallet(account_key, delta, currency=None):
    """Add delta (can be negative) to a wallet balance. Returns new balance or None."""
    if not account_key or account_key not in ("cash", "momo", "bank"):
        return None
    data = load_receiving_accounts()
    wallets = data.get("wallets") or {}
    w = wallets.get(account_key) or {"label": account_key, "balance": 0.0, "currency": "GHS"}
    try:
        bal = float(w.get("balance") or 0)
    except Exception:
        bal = 0.0
    bal = round(bal + float(delta or 0), 2)
    w["balance"] = bal
    if currency:
        w["currency"] = currency
    wallets[account_key] = w
    data["wallets"] = wallets
    save_receiving_accounts(data)
    return bal




def wallet_effect_expense(row):
    """Return (account, delta) that was applied for an expense row, or (None, 0)."""
    if not row:
        return None, 0.0
    if (row.get("status") or "") != "Paid":
        return None, 0.0
    acc = (row.get("account") or "").strip()
    if not acc:
        return None, 0.0
    try:
        amt = float(row.get("amount") or 0)
    except Exception:
        amt = 0.0
    return acc, -amt  # expense reduces balance


def wallet_effect_income(row):
    if not row:
        return None, 0.0
    if (row.get("status") or "") not in ("Received", "Cleared"):
        return None, 0.0
    acc = (row.get("account") or "").strip()
    if not acc:
        return None, 0.0
    try:
        amt = float(row.get("amount") or 0)
    except Exception:
        amt = 0.0
    return acc, amt  # income increases balance


def reapply_wallet(old_effect, new_effect, currency=None):
    """Undo old (account, delta) and apply new (account, delta)."""
    old_acc, old_delta = old_effect
    new_acc, new_delta = new_effect
    if old_acc and old_delta:
        adjust_wallet(old_acc, -old_delta, currency)  # reverse
    if new_acc and new_delta:
        adjust_wallet(new_acc, new_delta, currency)



def rebuild_wallet_balances():
    """Recalculate Cash/MoMo/Bank from expenses + incomes.

    Invoice payments that already created an Income row must NOT be counted again.
    Only invoice payment lines without a linked income_id are applied separately.
    """
    data = load_receiving_accounts()
    wallets = data.get("wallets") or {}
    labels = {"cash": "Cash on Hand", "momo": "Mobile Money", "bank": "Bank Account"}
    for key in ("cash", "momo", "bank"):
        prev = wallets.get(key) if isinstance(wallets.get(key), dict) else {}
        wallets[key] = {
            "label": prev.get("label") or labels[key],
            "balance": 0.0,
            "currency": prev.get("currency") or "GHS",
        }

    n_exp = n_inc = n_pay = 0

    def _acc(val):
        a = (val or "").strip().lower()
        if a in ("cash", "momo", "bank"):
            return a
        if "momo" in a or "mobile" in a:
            return "momo"
        if "cash" in a:
            return "cash"
        if "bank" in a:
            return "bank"
        return ""

    def _amt(row):
        try:
            return float(row.get("amount") or 0)
        except Exception:
            return 0.0

    # 1) Expenses (Paid) → debit wallet
    try:
        expenses = ops.list_expenses(limit=5000) if hasattr(ops, "list_expenses") else (ops.get_all("expenses") or [])
        for e in expenses:
            if (e.get("status") or "").strip().lower() != "paid":
                continue
            acc = _acc(e.get("account"))
            if not acc:
                continue
            wallets[acc]["balance"] = round(wallets[acc]["balance"] - _amt(e), 2)
            n_exp += 1
    except Exception as ex:
        print(f"[WaveTies] rebuild expenses: {ex}", flush=True)

    # 2) Incomes (Received/Cleared) → credit wallet (includes Invoice Payment incomes)
    try:
        incomes = ops.list_incomes(limit=5000) if hasattr(ops, "list_incomes") else (ops.get_all("incomes") or [])
        for i in incomes:
            if (i.get("status") or "").strip().lower() not in ("received", "cleared"):
                continue
            acc = _acc(i.get("account"))
            if not acc:
                continue
            wallets[acc]["balance"] = round(wallets[acc]["balance"] + _amt(i), 2)
            n_inc += 1
    except Exception as ex:
        print(f"[WaveTies] rebuild incomes: {ex}", flush=True)

    # 3) Invoice payments ONLY if they did not already create an income row
    try:
        db = load_db()
        for inv in (db.get("invoices") or {}).values():
            for pay in inv.get("payments") or []:
                if (pay.get("income_id") or "").strip():
                    continue  # already counted via income
                acc = _acc(pay.get("account"))
                if not acc:
                    continue
                try:
                    amt = float(pay.get("amount") or 0)
                except Exception:
                    amt = 0.0
                wallets[acc]["balance"] = round(wallets[acc]["balance"] + amt, 2)
                n_pay += 1
    except Exception as ex:
        print(f"[WaveTies] rebuild invoice pays: {ex}", flush=True)

    # 4) Ops payment register — skip if an expense already references this payment_id
    n_ops = 0
    try:
        exp_refs = set()
        try:
            for e in (ops.list_expenses(limit=5000) if hasattr(ops, "list_expenses") else []):
                ref = (e.get("reference") or "").strip()
                if ref:
                    exp_refs.add(ref)
        except Exception:
            pass
        for p in (ops.get_all("payments") or []):
            pid = (p.get("payment_id") or "").strip()
            if pid and pid in exp_refs:
                continue  # already counted as expense
            acc = _acc(p.get("account"))
            if not acc:
                notes = (p.get("notes") or "")
                if "account=" in notes:
                    acc = _acc(notes.split("account=")[-1].split()[0].strip(" ·,"))
            if not acc:
                continue
            try:
                amt = float(p.get("amount") or 0)
            except Exception:
                amt = 0.0
            direction = (p.get("direction") or "IN").strip().upper()
            if direction == "OUT":
                wallets[acc]["balance"] = round(wallets[acc]["balance"] - amt, 2)
            else:
                wallets[acc]["balance"] = round(wallets[acc]["balance"] + amt, 2)
            n_ops += 1
    except Exception as ex:
        print(f"[WaveTies] rebuild ops payments: {ex}", flush=True)

    data["wallets"] = wallets
    try:
        save_receiving_accounts(data)
    except Exception as ex:
        print(f"[WaveTies] save wallets failed: {ex}", flush=True)
    print(
        f"[WaveTies] Wallets rebuilt: exp={n_exp} inc={n_inc} pay_only={n_pay} ops={n_ops} "
        f"momo={wallets['momo']['balance']} cash={wallets['cash']['balance']} bank={wallets['bank']['balance']}",
        flush=True,
    )
    return wallets, n_exp, n_inc, n_pay




def period_date_range(period, start=None, end=None):
    """Return (start_date, end_date, label) for report presets."""
    today = datetime.now().date()
    if period == "custom" and start and end:
        return start, end, f"{start} to {end}"
    if period == "today":
        d = today.isoformat()
        return d, d, "Today"
    if period == "week":
        start_d = today - timedelta(days=today.weekday())  # Monday
        return start_d.isoformat(), today.isoformat(), "This week"
    if period == "year":
        return f"{today.year}-01-01", today.isoformat(), f"Year {today.year}"
    # default month
    start_d = today.replace(day=1)
    return start_d.isoformat(), today.isoformat(), today.strftime("%B %Y")





@app.route("/admin/accounts/rebuild-wallets", methods=["POST"])
@login_required
@admin_required
def admin_rebuild_wallets():
    wallets, n_exp, n_inc, n_pay = rebuild_wallet_balances()
    parts = [f"{k}: {w.get('currency','')} {float(w.get('balance') or 0):.2f}" for k, w in wallets.items()]
    flash(
        f"Balances rebuilt from {n_exp} expense(s), {n_inc} income(s), {n_pay} invoice payment(s). "
        + " · ".join(parts),
        "success",
    )
    return redirect(url_for("admin_treasury"))



@app.route("/admin/rates", methods=["GET", "POST"])
@login_required
@admin_required
def admin_fx_rates():
    """Live exchange rates: units of each currency per 1 USD."""
    main_curs = ["GHS", "CNY", "EUR", "GBP", "NGN", "KES", "ZAR", "AED", "USD"]
    if request.method == "POST":
        rates = ops.get_fx_rates()
        for cur in main_curs:
            if cur == "USD":
                continue
            raw = request.form.get(f"rate_{cur}", "").strip()
            if raw == "":
                continue
            try:
                rates[cur] = float(raw)
            except Exception:
                flash(f"Invalid rate for {cur}.", "danger")
                return redirect(url_for("admin_fx_rates"))
        # extra custom pair
        extra_cur = (request.form.get("extra_currency") or "").strip().upper()
        extra_rate = (request.form.get("extra_rate") or "").strip()
        if extra_cur and extra_rate:
            try:
                rates[extra_cur] = float(extra_rate)
            except Exception:
                flash(f"Invalid rate for {extra_cur}.", "danger")
                return redirect(url_for("admin_fx_rates"))
        as_of = (request.form.get("as_of") or datetime.now().strftime("%Y-%m-%d")).strip()
        ops.set_fx_rates(rates, as_of=as_of)
        recalc = request.form.get("recalc_usd") in ("1", "on", "yes")
        msg = f"Exchange rates saved for {as_of}."
        if recalc:
            ni, ne = ops.recalc_usd_amounts()
            msg += f" Recalculated USD on {ni} income(s) and {ne} expense(s)."
        flash(msg, "success")
        return redirect(url_for("admin_fx_rates"))
    rates = ops.get_fx_rates()
    as_of = ops.get_fx_as_of() or datetime.now().strftime("%Y-%m-%d")
    # example conversions
    examples = []
    ghs_rate = float(rates.get("GHS") or 0)
    if ghs_rate > 0:
        examples.append({"label": "GHS 1,000 → USD", "value": f"${ops.to_usd(1000, 'GHS'):,.2f}"})
        examples.append({"label": "USD 100 → GHS", "value": f"GHS {ops.from_usd(100, 'GHS'):,.2f}"})
    return render_template(
        "admin_fx_rates.html",
        rates=rates,
        as_of=as_of,
        main_curs=[c for c in main_curs if c != "USD"],
        examples=examples,
        company=COMPANY,
        user=session,
    )


@app.route("/admin/accounts", methods=["GET", "POST"])
@login_required
@finance_required
def admin_treasury():
    if request.method == "POST":
        bank_lines = [
            line.strip()
            for line in (request.form.get("bank_details") or "").splitlines()
            if line.strip()
        ]
        existing = load_receiving_accounts()
        wallets = existing.get("wallets") or {}
        for key in ("cash", "momo", "bank"):
            try:
                bal = float(request.form.get(f"wallet_{key}_balance", wallets.get(key, {}).get("balance", 0)) or 0)
            except Exception:
                bal = float((wallets.get(key) or {}).get("balance") or 0)
            cur = (request.form.get(f"wallet_{key}_currency") or (wallets.get(key) or {}).get("currency") or "GHS").strip().upper()
            label = (wallets.get(key) or {}).get("label") or key
            wallets[key] = {"label": label, "balance": bal, "currency": cur}
        data = {
            "momo_provider": request.form.get("momo_provider") or "TELECEL CASH",
            "momo": request.form.get("momo", "").strip(),
            "bank_lines": bank_lines,
            "contact_phone": request.form.get("contact_phone", "").strip(),
            "billing_email": request.form.get("billing_email", "").strip(),
            "internal_notes": request.form.get("internal_notes", "").strip(),
            "preferred_currency": (request.form.get("preferred_currency") or "USD").strip().upper(),
            "wallets": wallets,
        }
        save_receiving_accounts(data)
        # Keep invoice defaults in sync for new invoices
        COMPANY["momo"] = data["momo"]
        COMPANY["bank_lines"] = data["bank_lines"]
        if data["contact_phone"]:
            COMPANY["phone"] = data["contact_phone"]
        if data["billing_email"]:
            COMPANY["email"] = data["billing_email"]
        flash("Receiving account details saved.", "success")
        return redirect(url_for("admin_treasury"))

    accounts = load_receiving_accounts()
    accounts["bank_text"] = "\n".join(accounts.get("bank_lines") or [])
    # Always sync wallets from transactions (expenses/incomes/invoice payments)
    try:
        wallets, n_exp, n_inc, n_pay = rebuild_wallet_balances()
        accounts = load_receiving_accounts()
        accounts["bank_text"] = chr(10).join(accounts.get("bank_lines") or [])
    except Exception as _heal:
        print(f"[WaveTies] wallet sync: {_heal}", flush=True)


    db = load_db()
    invoices = db.get("invoices", {})
    invoice_paid = sum(float(i.get("paid") or 0) for i in invoices.values())
    outstanding = sum(max(0, float(i.get("balance_due") or 0)) for i in invoices.values())
    invoiced = sum(float(i.get("total") or 0) for i in invoices.values())

    try:
        ops_stats = ops.ops_kpis()
        ops_in = float(ops_stats.get("total_in") or 0)
    except Exception:
        ops_in = 0.0

    payment_rows = []
    for inv_no, inv in invoices.items():
        for p in inv.get("payments") or []:
            payment_rows.append({
                "invoice_no": inv_no,
                "customer": inv.get("customer_name", ""),
                "amount": float(p.get("amount") or 0),
                "currency": inv.get("currency") or "GHS",
                "by": p.get("by") or "—",
                "at": p.get("at") or "",
                "note": p.get("note") or "",
            })
    payment_rows.sort(key=lambda r: r["at"], reverse=True)
    payment_rows = payment_rows[:50]

    # Preferred display currency + per-currency breakdown
    preferred = accounts.get("preferred_currency") or "USD"
    by_currency = {}
    for inv in invoices.values():
        cur = (inv.get("currency") or preferred).upper()
        entry = by_currency.setdefault(cur, {"paid": 0.0, "outstanding": 0.0, "invoiced": 0.0})
        entry["paid"] += float(inv.get("paid") or 0)
        entry["outstanding"] += max(0.0, float(inv.get("balance_due") or 0))
        entry["invoiced"] += float(inv.get("total") or 0)

    return render_template(
        "admin_treasury.html",
        accounts=accounts,
        providers=MOMO_PROVIDERS,
        totals={
            "invoice_paid": invoice_paid,
            "outstanding": outstanding,
            "invoiced": invoiced,
            "ops_in": ops_in,
        },
        payment_rows=payment_rows,
        currency=preferred,
        by_currency=by_currency,
        currencies=CURRENCIES,
        company=COMPANY,
        user=session,
    )


@app.route("/admin/reset-data", methods=["GET", "POST"])
@login_required
@admin_required
def admin_reset_data():
    """Admin-only: wipe sample/live commercial data to start from zero."""
    if request.method == "POST":
        confirm = (request.form.get("confirm") or "").strip().upper()
        if confirm != "RESET":
            flash('Type RESET in capitals to confirm.', "danger")
            return redirect(url_for("admin_reset_data"))
        clear_clients = bool(request.form.get("clear_clients"))
        # Invoices
        db = load_db()
        inv_count = len(db.get("invoices", {}))
        db["invoices"] = {}
        db["next_invoice_seq"] = 1
        if clear_clients:
            db["customers"] = {}
        save_db(db)
        # Ops tables
        with ops.get_conn() as conn:
            for table in ("payments", "shipments", "rmb_txns", "sourcing", "orders", "expenses", "incomes"):
                conn.execute(f"DELETE FROM {table}")
            if clear_clients:
                conn.execute("DELETE FROM clients")
        # PDFs
        removed_pdfs = 0
        for p in OUTPUT_DIR.glob("Invoice_*.pdf"):
            try:
                p.unlink()
                removed_pdfs += 1
            except Exception:
                pass
        flash(
            f"Data cleared. Removed {inv_count} invoice(s) and operational records"
            + (" + clients/customers" if clear_clients else "")
            + f". PDFs removed: {removed_pdfs}. Balances are zero.",
            "success",
        )
        return redirect(url_for("dashboard"))
    return render_template(
        "admin_reset.html",
        company=COMPANY,
        user=session,
    )


@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    return render_template("admin_users.html", users=list_users(), company=COMPANY, user=session, role_labels=ROLE_LABELS, roles=ROLES)


@app.route("/admin/users/new", methods=["GET", "POST"])
@login_required
@admin_required
def admin_user_new():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        name = request.form.get("name", "").strip()
        role = normalize_role(request.form.get("role", "receptionist"))
        if not username or not password or not name:
            flash("All fields are required.", "danger")
            return redirect(url_for("admin_user_new"))
        if get_user(username):
            flash("Username already exists.", "danger")
            return redirect(url_for("admin_user_new"))
        conn = get_users_db()
        selected = request.form.getlist("permissions")
        if not selected:
            selected = permissions_for_role(role)
        if role == "admin":
            selected = list(PERM_KEYS)
        import json as _json
        perms_json = _json.dumps(selected)
        try:
            conn.execute(
                "INSERT INTO users (username, password_hash, name, role, created_at, permissions) VALUES (?,?,?,?,?,?)",
                (username, generate_password_hash(password), name, role, datetime.now().isoformat(timespec="seconds"), perms_json)
            )
        except Exception:
            conn.execute(
                "INSERT INTO users (username, password_hash, name, role, created_at) VALUES (?,?,?,?,?)",
                (username, generate_password_hash(password), name, role, datetime.now().isoformat(timespec="seconds"))
            )
        conn.commit()
        conn.close()
        flash(f"User {username} created with {len(selected)} permission(s).", "success")
        return redirect(url_for("admin_users"))
    return render_template(
        "admin_user_form.html",
        edit_user=None,
        company=COMPANY,
        user=session,
        roles=ROLES,
        all_permissions=PERMISSIONS,
        selected_permissions=permissions_for_role("receptionist"),
        role_defaults=ROLE_DEFAULT_PERMISSIONS,
    )


@app.route("/admin/users/<int:uid>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def admin_user_edit(uid):
    conn = get_users_db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        conn.close()
        flash("User not found.", "danger")
        return redirect(url_for("admin_users"))
    edit_user = dict(row)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        role = normalize_role(request.form.get("role", "receptionist"))
        password = request.form.get("password", "")
        active = 1 if request.form.get("active") else 0
        selected = request.form.getlist("permissions")
        if not selected:
            selected = permissions_for_role(role)
        if role == "admin":
            selected = list(PERM_KEYS)
        import json as _json
        perms_json = _json.dumps(selected)
        if password:
            try:
                conn.execute(
                    "UPDATE users SET name=?, role=?, active=?, password_hash=?, permissions=? WHERE id=?",
                    (name, role, active, generate_password_hash(password), perms_json, uid)
                )
            except Exception:
                conn.execute(
                    "UPDATE users SET name=?, role=?, active=?, password_hash=? WHERE id=?",
                    (name, role, active, generate_password_hash(password), uid)
                )
        else:
            try:
                conn.execute(
                    "UPDATE users SET name=?, role=?, active=?, permissions=? WHERE id=?",
                    (name, role, active, perms_json, uid)
                )
            except Exception:
                conn.execute("UPDATE users SET name=?, role=?, active=? WHERE id=?", (name, role, active, uid))
        conn.commit()
        conn.close()
        flash("User updated (permissions saved).", "success")
        return redirect(url_for("admin_users"))
    conn.close()
    selected = parse_permissions(edit_user.get("permissions"))
    if not selected:
        selected = permissions_for_role(edit_user.get("role"))
    return render_template(
        "admin_user_form.html",
        edit_user=edit_user,
        company=COMPANY,
        user=session,
        roles=ROLES,
        all_permissions=PERMISSIONS,
        selected_permissions=selected,
        role_defaults=ROLE_DEFAULT_PERMISSIONS,
    )



@app.route("/admin/users/<int:uid>/role", methods=["POST"])
@login_required
@admin_required
def admin_user_set_role(uid):
    """Quick role assignment from the Users list."""
    role = normalize_role(request.form.get("role", "receptionist"))
    if role not in ROLE_LABELS and role != "worker":
        flash("Invalid role.", "danger")
        return redirect(url_for("admin_users"))
    conn = get_users_db()
    row = conn.execute("SELECT id, username FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        conn.close()
        flash("User not found.", "danger")
        return redirect(url_for("admin_users"))
    conn.execute("UPDATE users SET role=? WHERE id=?", (role, uid))
    conn.commit()
    conn.close()
    flash(f"Role for {row['username']} set to {ROLE_LABELS.get(role, role)}.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/smtp", methods=["GET", "POST"])
@login_required
@admin_required
def admin_smtp():
    cfg = load_smtp_config()
    if request.method == "POST":
        cfg = {
            "host": request.form.get("host", "").strip(),
            "port": int(request.form.get("port", 587) or 587),
            "user": request.form.get("user", "").strip(),
            "password": request.form.get("password", "").strip() or cfg.get("password", ""),
            "from_email": request.form.get("from_email", "").strip(),
            "use_tls": bool(request.form.get("use_tls")),
        }
        save_smtp_config(cfg)
        flash("SMTP settings saved.", "success")
        return redirect(url_for("admin_smtp"))
    return render_template("admin_smtp.html", cfg=cfg, company=COMPANY, user=session)




# ──────────────────────────────────────────────────────────────
# OPERATIONS: Clients, Orders, Payments, Shipments, RMB, Sourcing
# ──────────────────────────────────────────────────────────────

ORDER_STATUSES = ["Inquiry", "Confirmed", "Payment Pending", "Paid / Processing",
                  "In Transit", "Delivered", "Closed", "Cancelled", "On Hold"]
SERVICE_TYPES = ["SHIP", "SRC", "BFM", "RMB", "PAY", "VAL", "COMBO"]
SERVICE_LABELS = {
    "SHIP": "Shipping", "SRC": "Sourcing", "BFM": "Buy For Me",
    "RMB": "RMB / Yuan", "PAY": "Payment", "VAL": "Valuation", "COMBO": "Combo Service",
}
DEFAULT_BFM_FEE_PERCENT = 5.0


def get_bfm_fee_percent():
    try:
        return float(ops.get_setting("bfm_fee_percent", str(DEFAULT_BFM_FEE_PERCENT)))
    except Exception:
        return DEFAULT_BFM_FEE_PERCENT


def get_bfm_fee_rate():
    return get_bfm_fee_percent() / 100.0

PAY_STATUSES = ["Unpaid", "Partial", "Paid", "Refunded", "Waived"]
CURRENCIES = ["USD", "EUR", "GBP", "CNY", "JPY", "CHF", "CAD", "AUD", "NZD", "INR", "AED", "SAR", "QAR", "KWD", "BHD", "OMR", "SGD", "HKD", "KRW", "TWD", "THB", "MYR", "IDR", "PHP", "VND", "TRY", "RUB", "BRL", "MXN", "ARS", "CLP", "COP", "PEN", "EGP", "MAD", "TND", "DZD", "LYD", "SDG", "SSP", "NGN", "GHS", "XOF", "GMD", "SLL", "LRD", "GNF", "CVE", "MRU", "XAF", "CDF", "AOA", "STN", "KES", "TZS", "UGX", "RWF", "BIF", "ETB", "SOS", "DJF", "ERN", "SCR", "KMF", "MGA", "MUR", "ZAR", "BWP", "NAD", "ZMW", "MWK", "MZN", "SZL", "LSL", "ZWL"]
INCOTERMS = ["EXW", "FCA", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP", "—"]
CLIENT_TYPES = ["Importer", "Exporter", "Distributor", "SME", "Corporate", "Sourcing Agent", "Other"]
SHIP_MODES = ["Sea FCL", "Sea LCL", "Air", "Road", "Rail", "Multimodal"]
SHIP_STATUSES = ["Booked", "Departed Origin", "In Transit", "Arrived Dest", "Customs",
                 "Out for Delivery", "Delivered", "Exception"]
PAY_TYPES = ["Order Payment", "RMB Exchange", "Supplier Payment", "Owner Capital", "Owner Loan", "Refund", "Fee", "Other"]
PAY_METHODS = ["Bank Transfer", "Mobile Money", "Cash", "Alipay", "WeChat Pay", "Credit", "Other"]
RMB_TYPES = ["Client Exchange", "Supplier Payment", "Internal Transfer", "Other"]
SRC_STATUSES = ["Request Received", "Sourcing", "Quotes Obtained", "Quote Sent to Client",
                "Quote Accepted", "PO Issued", "Goods Ready", "Cancelled"]


@app.route("/ops/clients")
@login_required
def ops_clients():
    clients = ops.client_list()
    return render_template("ops_clients.html", clients=clients, company=COMPANY, user=session,
                           client_types=CLIENT_TYPES, currencies=CURRENCIES)


@app.route("/ops/clients/new", methods=["POST"])
@login_required
def ops_client_new():
    company = request.form.get("company_name", "").strip()
    if not company:
        flash("Company name is required.", "danger")
        return redirect(url_for("ops_clients"))
    try:
        cid = ops.next_id("C", "clients", "client_id")
        ops.insert("clients", {
            "client_id": cid,
            "date_registered": datetime.now().strftime("%Y-%m-%d"),
            "company_name": company,
            "contact_person": request.form.get("contact_person", ""),
            "phone": request.form.get("phone", ""),
            "email": request.form.get("email", ""),
            "country": request.form.get("country", ""),
            "city": request.form.get("city", ""),
            "client_type": request.form.get("client_type", "Importer"),
            "preferred_currency": request.form.get("preferred_currency", "USD"),
            "credit_terms": int(request.form.get("credit_terms", 0) or 0),
            "status": "Active",
            "notes": request.form.get("notes", ""),
        })
        flash(f"Client {cid} registered.", "success")
    except Exception as e:
        flash(f"Could not create client: {e}", "danger")
    return redirect(url_for("ops_clients"))


@app.route("/ops/clients/<client_id>/edit", methods=["GET", "POST"])
@login_required
@manage_required
def ops_client_edit(client_id):
    client = ops.get_one("clients", "client_id", client_id)
    if not client:
        flash("Client not found.", "danger")
        return redirect(url_for("ops_clients"))
    if request.method == "POST":
        company = request.form.get("company_name", "").strip()
        if not company:
            flash("Company name is required.", "danger")
            return redirect(url_for("ops_client_edit", client_id=client_id))
        ops.update("clients", "client_id", client_id, {
            "company_name": company,
            "contact_person": request.form.get("contact_person", ""),
            "phone": request.form.get("phone", ""),
            "email": request.form.get("email", ""),
            "country": request.form.get("country", ""),
            "city": request.form.get("city", ""),
            "client_type": request.form.get("client_type", "Importer"),
            "preferred_currency": request.form.get("preferred_currency", "USD"),
            "credit_terms": int(request.form.get("credit_terms", 0) or 0),
            "status": request.form.get("status", "Active"),
            "notes": request.form.get("notes", ""),
        })
        flash(f"Client {client_id} updated.", "success")
        return redirect(url_for("ops_clients"))
    return render_template(
        "ops_client_edit.html",
        client=client,
        company=COMPANY,
        user=session,
        client_types=CLIENT_TYPES,
        currencies=CURRENCIES,
        statuses=["Active", "Inactive", "Suspended", "Prospect"],
    )


@app.route("/ops/clients/<client_id>/delete", methods=["POST"])
@login_required
@manage_required
def ops_client_delete(client_id):
    client = ops.get_one("clients", "client_id", client_id)
    if not client:
        flash("Client not found.", "danger")
        return redirect(url_for("ops_clients"))
    # Block delete if client has orders
    orders = [o for o in ops.order_list() if o.get("client_id") == client_id]
    if orders:
        flash(
            f"Cannot delete {client_id}: {len(orders)} order(s) linked. "
            "Set status to Inactive instead, or reassign orders first.",
            "danger",
        )
        return redirect(url_for("ops_clients"))
    ops.delete("clients", "client_id", client_id)
    flash(f"Client {client_id} ({client.get('company_name','')}) deleted.", "success")
    return redirect(url_for("ops_clients"))



@app.route("/ops/orders")
@login_required
def ops_orders():
    orders = ops.order_list()
    clients = {c["client_id"]: c["company_name"] for c in ops.client_list()}
    return render_template("ops_orders.html", orders=orders, clients=clients,
                           company=COMPANY, user=session,
                           statuses=ORDER_STATUSES, services=SERVICE_TYPES,
                           service_labels=SERVICE_LABELS,
                           bfm_fee_percent=get_bfm_fee_percent(),
                           currencies=CURRENCIES, incoterms=INCOTERMS)


@app.route("/ops/orders/new", methods=["POST"])
@login_required
def ops_order_new():
    desc = request.form.get("description", "").strip()
    client_id = request.form.get("client_id", "").strip()
    if not desc or not client_id:
        flash("Client and description are required.", "danger")
        return redirect(url_for("ops_orders"))
    custom_oid = (request.form.get("order_id_custom") or "").strip().upper()
    if custom_oid:
        existing = ops.get_one("orders", "order_id", custom_oid)
        if existing:
            flash(f"Order ID {custom_oid} already exists.", "danger")
            return redirect(url_for("ops_orders"))
        oid = custom_oid
    else:
        oid = ops.next_id("ORD", "orders", "order_id")
    ops.insert("orders", {
        "order_id": oid,
        "order_date": request.form.get("order_date") or datetime.now().strftime("%Y-%m-%d"),
        "client_id": client_id,
        "service_type": request.form.get("service_type", "SHIP"),
        "description": desc,
        "origin": request.form.get("origin", ""),
        "destination": request.form.get("destination", ""),
        "incoterm": request.form.get("incoterm", "FOB"),
        "currency": request.form.get("currency", "USD"),
        "order_value": float(request.form.get("order_value", 0) or 0),
        "status": "Inquiry",
        "payment_status": "Unpaid",
        "value_usd": float(request.form.get("value_usd", 0) or 0),
        "assigned_to": request.form.get("assigned_to", "Ops Team"),
        "expected_delivery": request.form.get("expected_delivery", ""),
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
        "invoice_no": "",
        "notes": request.form.get("notes", ""),
    })
    flash(f"Order {oid} created.", "success")
    return redirect(url_for("ops_orders"))


@app.route("/ops/orders/<order_id>/delete", methods=["POST"])
@login_required
@manage_required
def ops_order_delete(order_id):
    order = ops.get_one("orders", "order_id", order_id)
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for("ops_orders"))
    ops.delete("orders", "order_id", order_id)
    flash(f"Order {order_id} deleted.", "success")
    return redirect(url_for("ops_orders"))


@app.route("/ops/orders/<order_id>/status", methods=["POST"])
@login_required
@ops_status_required
def ops_order_status(order_id):
    order = ops.get_one("orders", "order_id", order_id)
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for("ops_orders"))
    ops.update("orders", "order_id", order_id, {
        "status": request.form.get("status", order["status"]),
        "payment_status": request.form.get("payment_status", order["payment_status"]),
        "notes": request.form.get("notes", order.get("notes") or ""),
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
    })
    flash(f"Order {order_id} updated.", "success")
    return redirect(url_for("ops_orders"))


def _bfm_invoice_items(order, order_id, amount, form):
    """Build invoice line items; for BFM optionally add service charge % on total."""
    items = [{
        "tracking": form.get("tracking") or order_id,
        "item_name": order.get("description") or "Logistics services",
        "transport": form.get("transport") or (
            "SEA_FREIGHT" if order.get("service_type") == "SHIP" else "OTHER"
        ),
        "boxes": int(form.get("boxes", 1) or 1),
        "weight_kg": float(form.get("weight_kg", 0) or 0),
        "vol_cbm": float(form.get("vol_cbm", 0) or 0),
        "order_number": order_id,
        "amount": amount,
    }]
    is_bfm = (order.get("service_type") or "").upper() == "BFM"
    apply = form.get("apply_bfm_fee") in ("1", "on", "yes", "true")
    if is_bfm and apply:
        try:
            pct = float(form.get("bfm_fee_percent") or get_bfm_fee_percent())
        except Exception:
            pct = get_bfm_fee_percent()
        fee = round(float(amount or 0) * (pct / 100.0), 2)
        if fee > 0:
            items.append({
                "tracking": form.get("tracking") or order_id,
                "item_name": f"BFM service charge ({pct:g}%)",
                "transport": "OTHER",
                "boxes": 0,
                "weight_kg": 0,
                "vol_cbm": 0,
                "order_number": order_id,
                "amount": fee,
            })
    return items


@app.route("/ops/orders/<order_id>/invoice", methods=["GET", "POST"])
@login_required
def ops_order_to_invoice(order_id):
    """Create an invoice pre-filled from an order."""
    order = ops.get_one("orders", "order_id", order_id)
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for("ops_orders"))
    client = ops.get_one("clients", "client_id", order["client_id"]) or {}
    if request.method == "POST":
        try:
            inv_date = datetime.now()
            due_days = int(request.form.get("due_days", 30) or 30)
            due_date = inv_date + timedelta(days=due_days)
            amount = float(request.form.get("amount", order.get("order_value") or 0) or 0)
            ra = load_receiving_accounts()
            momo_provider = (request.form.get("momo_provider") or "").strip()
            if not momo_provider:
                momo_provider = ra.get("momo_provider") or "TELECEL CASH"
            momo_val = (request.form.get("momo") or "").strip() or ra.get("momo") or COMPANY.get("momo", "")
            bank_src = request.form.get("bank_details")
            if bank_src is None or not str(bank_src).strip():
                bank_src = "\n".join(ra.get("bank_lines") or COMPANY.get("bank_lines", []))
            currency = (request.form.get("currency") or order.get("currency") or "USD").strip().upper()
            data = {
                "customer_name": client.get("company_name") or order["client_id"],
                "customer_email": client.get("email") or "",
                "customer_phone": client.get("phone") or "",
                "invoice_date": inv_date.strftime("%b %d, %Y"),
                "due_date": due_date.strftime("%b %d, %Y"),
                "currency": currency,
                "tax": float(request.form.get("tax", 0) or 0),
                "paid": float(request.form.get("paid", 0) or 0),
                "items": _bfm_invoice_items(order, order_id, amount, request.form),
                "momo": momo_val,
                "momo_provider": momo_provider,
                "bank_lines": [
                    line.strip()
                    for line in str(bank_src).splitlines()
                    if line.strip()
                ],
                "contact_phone": ra.get("contact_phone") or COMPANY.get("phone"),
            }
            inv_no = create_invoice(data, created_by=session.get("username", "worker"))
            ops.update("orders", "order_id", order_id, {
                "invoice_no": inv_no,
                "last_updated": datetime.now().strftime("%Y-%m-%d"),
            })
            flash(f"Invoice {inv_no} created from order {order_id} ({momo_provider}).", "success")
            return redirect(url_for("view_invoice", invoice_no=inv_no))
        except Exception as e:
            flash(f"Error: {e}", "danger")
            return redirect(url_for("ops_order_to_invoice", order_id=order_id))
    ra = load_receiving_accounts()
    bfm_pct = get_bfm_fee_percent()
    base_amt = float(order.get("order_value") or 0)
    is_bfm = (order.get("service_type") or "").upper() == "BFM"
    bfm_fee_preview = round(base_amt * (bfm_pct / 100.0), 2) if is_bfm else 0.0
    return render_template(
        "ops_order_invoice.html",
        order=order, client=client, company=COMPANY, user=session,
        bfm_fee_percent=bfm_pct,
        bfm_fee_preview=bfm_fee_preview,
        is_bfm=is_bfm,
        default_momo=ra.get("momo") or COMPANY.get("momo", ""),
        default_bank="\n".join(ra.get("bank_lines") or COMPANY.get("bank_lines", [])),
        default_momo_provider=ra.get("momo_provider") or "TELECEL CASH",
        currencies=CURRENCIES,
    )


@app.route("/ops/payments")
@login_required
def ops_payments():
    payments = ops.get_all("payments", order_by="pay_date DESC")
    kpis = ops.ops_kpis()
    clients = ops.client_list()
    orders = ops.order_list()
    ra = load_receiving_accounts()
    return render_template("ops_payments.html", payments=payments, kpis=kpis,
                           clients=clients, orders=orders, company=COMPANY, user=session,
                           pay_types=PAY_TYPES, pay_methods=PAY_METHODS, currencies=CURRENCIES,
                           accounts=ACCOUNT_OPTIONS, wallets=(ra.get("wallets") or {}))


@app.route("/ops/payments/new", methods=["POST"])
@login_required
def ops_payment_new():
    pid = ops.next_id("PAY", "payments", "payment_id")
    amount = float(request.form.get("amount", 0) or 0)
    amount_usd = float(request.form.get("amount_usd", 0) or 0)
    currency = (request.form.get("currency") or "USD").strip().upper()
    direction = (request.form.get("direction") or "IN").strip().upper()
    account = (request.form.get("account") or "").strip()
    pay_type = request.form.get("pay_type") or "Order Payment"
    if amount_usd <= 0 or (currency != "USD" and abs(amount_usd - amount) < 0.0001):
        amount_usd = ops.to_usd(amount, currency)
    elif currency == "USD":
        amount_usd = amount if amount_usd <= 0 else amount_usd
    notes = (request.form.get("notes") or "").strip()
    if account:
        notes = (notes + f" · account={account}").strip(" ·")
    # Require account for OUT so manufacturer pays hit MoMo/Bank
    if direction == "OUT" and not account:
        flash("Select Pay from account (Cash / MoMo / Bank) for supplier OUT payments.", "danger")
        return redirect(url_for("ops_payments"))
    row = {
        "payment_id": pid,
        "pay_date": request.form.get("pay_date") or datetime.now().strftime("%Y-%m-%d"),
        "order_id": form_order_id(),
        "client_id": request.form.get("client_id", ""),
        "pay_type": pay_type,
        "direction": direction,
        "currency": currency,
        "amount": amount,
        "amount_usd": amount_usd,
        "method": request.form.get("method", "Bank Transfer"),
        "reference": request.form.get("reference", ""),
        "bank_channel": request.form.get("bank_channel", ""),
        "recorded_by": session.get("username", "Finance"),
        "notes": notes,
        "account": account,
    }
    try:
        ops.insert("payments", row)
    except Exception:
        # Older DB without account column — insert without it
        row.pop("account", None)
        ops.insert("payments", row)
        try:
            ops.update("payments", "payment_id", pid, {"account": account})
        except Exception:
            pass

    expense_id = None
    # Supplier / manufacturer OUT also appears under Expenses (one wallet movement only)
    if direction == "OUT" and pay_type in (
        "Supplier Payment", "Fee", "Other"
    ):
        try:
            cat = "Supplier / Manufacturer Payment" if pay_type == "Supplier Payment" else "Miscellaneous"
            expense_id = ops.add_expense({
                "expense_date": row["pay_date"],
                "category": cat,
                "subcategory": (row.get("order_id") or "").strip(),
                "description": (request.form.get("notes") or f"{pay_type} {pid}").strip(),
                "payee": (request.form.get("bank_channel") or request.form.get("reference") or "Supplier").strip(),
                "worker_username": "",
                "amount": amount,
                "currency": currency,
                "amount_usd": amount_usd,
                "payment_method": request.form.get("method") or "Other",
                "reference": pid,  # links expense ↔ payment (avoid double-count on rebuild)
                "status": "Paid",
                "recorded_by": session.get("name") or session.get("username") or "Finance",
                "notes": f"Auto from payment {pid}",
                "account": account or "",
            })
        except Exception as ex:
            print(f"[WaveTies] auto expense from payment failed: {ex}", flush=True)

    # Update cash/MoMo/bank when account selected (single deduction)
    if account and amount:
        delta = amount if direction == "IN" else -amount
        new_bal = adjust_wallet(account, delta, currency)
        msg = (
            f"Payment {pid} recorded ({direction}). "
            f"{'Credited' if direction=='IN' else 'Deducted'} {currency} {amount:.2f} "
            f"on {account}. Balance now {currency} {new_bal if new_bal is not None else '?'}."
        )
        if expense_id:
            msg += f" Also listed under Expenses as {expense_id}."
        flash(msg, "success")
    else:
        msg = f"Payment {pid} recorded."
        if expense_id:
            msg += f" Listed under Expenses as {expense_id}."
        if direction == "OUT":
            msg += " Select an account so MoMo/Bank updates."
        flash(msg, "success" if expense_id else "warning")
    return redirect(url_for("ops_payments"))




@app.route("/ops/payments/<payment_id>/edit", methods=["GET", "POST"])
@login_required
@finance_required
def ops_payment_edit(payment_id):
    """Edit a payment; reverse old wallet effect and apply new; sync linked expense."""
    row = ops.get_one("payments", "payment_id", payment_id)
    if not row:
        flash("Payment not found.", "danger")
        return redirect(url_for("ops_payments"))
    clients = ops.client_list()
    orders = ops.order_list()
    ra = load_receiving_accounts()

    def _acc(val):
        a = (val or "").strip().lower()
        if a in ("cash", "momo", "bank"):
            return a
        return ""

    if request.method == "POST":
        try:
            old_acc = _acc(row.get("account"))
            try:
                old_amt = float(row.get("amount") or 0)
            except Exception:
                old_amt = 0.0
            old_dir = (row.get("direction") or "IN").strip().upper()

            amount = float(request.form.get("amount", 0) or 0)
            amount_usd = float(request.form.get("amount_usd", 0) or 0)
            currency = (request.form.get("currency") or row.get("currency") or "USD").strip().upper()
            direction = (request.form.get("direction") or "IN").strip().upper()
            account = (request.form.get("account") or "").strip()
            pay_type = request.form.get("pay_type") or row.get("pay_type") or "Other"
            if direction == "OUT" and not account:
                flash("Select Pay from account for OUT payments.", "danger")
                return redirect(url_for("ops_payment_edit", payment_id=payment_id))
            if amount_usd <= 0 or (currency != "USD" and abs(amount_usd - amount) < 0.0001):
                amount_usd = ops.to_usd(amount, currency)
            order_id = (request.form.get("order_id") or request.form.get("order_id_manual") or "").strip()

            data = {
                "pay_date": request.form.get("pay_date") or row.get("pay_date"),
                "order_id": order_id,
                "client_id": request.form.get("client_id") or "",
                "pay_type": pay_type,
                "direction": direction,
                "currency": currency,
                "amount": amount,
                "amount_usd": amount_usd,
                "method": request.form.get("method") or row.get("method") or "",
                "reference": request.form.get("reference") or "",
                "bank_channel": request.form.get("bank_channel") or "",
                "notes": request.form.get("notes") or "",
                "account": account,
            }
            ops.update("payments", "payment_id", payment_id, data)

            # Reverse old wallet, apply new
            if old_acc and old_amt:
                # old OUT deducted → reverse is +; old IN credited → reverse is -
                rev = old_amt if old_dir == "OUT" else -old_amt
                adjust_wallet(old_acc, rev, row.get("currency"))
            if account and amount:
                delta = amount if direction == "IN" else -amount
                adjust_wallet(account, delta, currency)

            # Sync linked expense (reference = payment_id)
            try:
                linked = None
                for e in (ops.list_expenses(limit=2000) if hasattr(ops, "list_expenses") else []):
                    if (e.get("reference") or "").strip() == payment_id:
                        linked = e
                        break
                if linked and direction == "OUT":
                    ops.update("expenses", "expense_id", linked["expense_id"], {
                        "expense_date": data["pay_date"],
                        "category": "Supplier / Manufacturer Payment" if pay_type == "Supplier Payment" else (linked.get("category") or "Miscellaneous"),
                        "subcategory": order_id,
                        "description": (data["notes"] or linked.get("description") or "").strip(),
                        "amount": amount,
                        "currency": currency,
                        "amount_usd": amount_usd,
                        "payment_method": data["method"],
                        "status": "Paid",
                        "account": account,
                    })
                elif linked and direction != "OUT":
                    # no longer a supplier outlay — leave expense or delete
                    pass
                elif not linked and direction == "OUT" and pay_type == "Supplier Payment":
                    ops.add_expense({
                        "expense_date": data["pay_date"],
                        "category": "Supplier / Manufacturer Payment",
                        "subcategory": order_id,
                        "description": (data["notes"] or f"Supplier Payment {payment_id}").strip(),
                        "payee": data.get("bank_channel") or data.get("reference") or "Supplier",
                        "amount": amount,
                        "currency": currency,
                        "amount_usd": amount_usd,
                        "payment_method": data["method"],
                        "reference": payment_id,
                        "status": "Paid",
                        "recorded_by": session.get("username") or "Finance",
                        "notes": f"Auto from payment {payment_id}",
                        "account": account,
                    })
            except Exception as ex:
                print(f"[WaveTies] payment edit expense sync: {ex}", flush=True)

            flash(f"Payment {payment_id} updated.", "success")
            return redirect(url_for("ops_payments"))
        except Exception as e:
            flash(f"Could not update payment: {e}", "danger")
            return redirect(url_for("ops_payment_edit", payment_id=payment_id))

    return render_template(
        "ops_payment_edit.html",
        payment=row,
        clients=clients,
        orders=orders,
        pay_types=PAY_TYPES,
        pay_methods=PAY_METHODS,
        currencies=CURRENCIES,
        accounts=ACCOUNT_OPTIONS,
        wallets=(ra.get("wallets") or {}),
        company=COMPANY,
        user=session,
    )


@app.route("/ops/payments/<payment_id>/delete", methods=["POST"])
@login_required
@finance_required
def ops_payment_delete(payment_id):
    row = ops.get_one("payments", "payment_id", payment_id)
    if not row:
        flash("Payment not found.", "danger")
        return redirect(url_for("ops_payments"))
    # reverse wallet
    acc = (row.get("account") or "").strip().lower()
    try:
        amt = float(row.get("amount") or 0)
    except Exception:
        amt = 0.0
    direction = (row.get("direction") or "IN").strip().upper()
    if acc in ("cash", "momo", "bank") and amt:
        rev = amt if direction == "OUT" else -amt
        adjust_wallet(acc, rev, row.get("currency"))
    # delete linked expense
    try:
        for e in (ops.list_expenses(limit=2000) if hasattr(ops, "list_expenses") else []):
            if (e.get("reference") or "").strip() == payment_id:
                # reverse expense wallet only if payment had no account (expense owned the wallet)
                # payment already reversed above if it had account; expense may have same account —
                # do not reverse expense wallet again if payment had account
                ops.delete("expenses", "expense_id", e["expense_id"])
                break
    except Exception as ex:
        print(f"[WaveTies] delete linked expense: {ex}", flush=True)
    ops.delete("payments", "payment_id", payment_id)
    flash(f"Payment {payment_id} deleted.", "success")
    return redirect(url_for("ops_payments"))


@app.route("/ops/shipments")
@login_required
def ops_shipments():
    ships = ops.get_all("shipments", order_by="etd DESC")
    orders = ops.order_list()
    clients = ops.client_list()
    return render_template("ops_shipments.html", shipments=ships, orders=orders,
                           clients=clients, company=COMPANY, user=session,
                           modes=SHIP_MODES, statuses=SHIP_STATUSES)


@app.route("/ops/shipments/new", methods=["POST"])
@login_required
def ops_shipment_new():
    sid = ops.next_id("SHP", "shipments", "shipment_id")
    ops.insert("shipments", {
        "shipment_id": sid,
        "order_id": form_order_id(),
        "client_id": request.form.get("client_id", ""),
        "mode": request.form.get("mode", "Sea FCL"),
        "carrier": request.form.get("carrier", ""),
        "bl_awb": request.form.get("bl_awb", ""),
        "container_tracking": request.form.get("container_tracking", ""),
        "origin_port": request.form.get("origin_port", ""),
        "dest_port": request.form.get("dest_port", ""),
        "etd": request.form.get("etd", ""),
        "eta": request.form.get("eta", ""),
        "atd": "", "ata": "",
        "status": "Booked",
        "weight_kg": float(request.form.get("weight_kg", 0) or 0),
        "cbm": float(request.form.get("cbm", 0) or 0),
        "notes": request.form.get("notes", ""),
    })
    flash(f"Shipment {sid} created.", "success")
    return redirect(url_for("ops_shipments"))


@app.route("/ops/shipments/<shipment_id>/status", methods=["POST"])
@login_required
@ops_status_required
def ops_shipment_status(shipment_id):
    ship = ops.get_one("shipments", "shipment_id", shipment_id)
    if not ship:
        flash("Shipment not found.", "danger")
        return redirect(url_for("ops_shipments"))
    data = {
        "status": request.form.get("status", ship["status"]),
        "notes": request.form.get("notes", ship.get("notes") or ""),
    }
    if request.form.get("atd"):
        data["atd"] = request.form.get("atd")
    if request.form.get("ata"):
        data["ata"] = request.form.get("ata")
    ops.update("shipments", "shipment_id", shipment_id, data)
    flash(f"Shipment {shipment_id} updated.", "success")
    return redirect(url_for("ops_shipments"))


@app.route("/ops/rmb")
@login_required
def ops_rmb():
    txns = ops.get_all("rmb_txns", order_by="txn_date DESC")
    rates = ops.get_rmb_rates()
    usd_rate = float(rates.get("USD") or ops.get_setting("rmb_rate", "7.14"))
    orders = ops.order_list()
    clients = ops.client_list()
    # Currencies for rate desk exclude CNY as base (rate is always vs CNY)
    rate_currencies = [c for c in CURRENCIES if c != "CNY"]
    return render_template(
        "ops_rmb.html",
        txns=txns,
        rates=rates,
        rate=usd_rate,
        orders=orders,
        clients=clients,
        company=COMPANY,
        user=session,
        rmb_types=RMB_TYPES,
        currencies=rate_currencies,
        all_rates=sorted(rates.items()),
    )


@app.route("/ops/rmb/rate", methods=["POST"])
@login_required
@manage_required
def ops_rmb_rate():
    currency = (request.form.get("currency") or "USD").strip().upper()
    rate = float(request.form.get("rate", 0) or 0)
    if rate <= 0:
        flash("Rate must be greater than zero.", "danger")
        return redirect(url_for("ops_rmb"))
    ops.set_rmb_rate_for(currency, rate)
    flash(f"Reference rate updated: 1 {currency} = {rate} CNY.", "success")
    return redirect(url_for("ops_rmb"))


@app.route("/ops/rmb/new", methods=["POST"])
@login_required
def ops_rmb_new():
    base_currency = (request.form.get("base_currency") or "USD").strip().upper()
    rates = ops.get_rmb_rates()
    default_rate = float(rates.get(base_currency) or rates.get("USD") or 7.14)
    rate = float(request.form.get("rate_used") or default_rate)
    cny = float(request.form.get("cny_amount", 0) or 0)
    # base_amount = how much of base currency equals this CNY at rate (CNY per 1 base)
    base_amount = round(cny / rate, 2) if rate else 0
    # Keep usd_amount for legacy dashboard: convert via USD rate if possible
    usd_rate = float(rates.get("USD") or 7.14)
    if base_currency == "USD":
        usd_amount = base_amount
    elif usd_rate:
        # cny/usd_rate = USD equivalent of the CNY leg
        usd_amount = round(cny / usd_rate, 2) if usd_rate else 0
    else:
        usd_amount = 0
    tid = ops.next_id("RMB", "rmb_txns", "txn_id")
    ops.insert("rmb_txns", {
        "txn_id": tid,
        "txn_date": request.form.get("txn_date") or datetime.now().strftime("%Y-%m-%d"),
        "order_id": form_order_id(),
        "client_id": request.form.get("client_id", ""),
        "txn_type": request.form.get("txn_type", "Client Exchange"),
        "cny_amount": cny,
        "usd_amount": usd_amount,
        "rate_used": rate,
        "base_currency": base_currency,
        "base_amount": base_amount,
        "direction": request.form.get("direction", ""),
        "counterparty": request.form.get("counterparty", ""),
        "channel": request.form.get("channel", ""),
        "status": request.form.get("status", "Pending"),
        "notes": request.form.get("notes", ""),
    })
    flash(f"RMB transaction {tid} recorded ({base_amount} {base_currency} → {cny} CNY @ {rate}).", "success")
    return redirect(url_for("ops_rmb"))


@app.route("/ops/sourcing")
@login_required
def ops_sourcing():
    items = ops.get_all("sourcing", order_by="src_date DESC")
    orders = ops.order_list()
    clients = ops.client_list()
    return render_template("ops_sourcing.html", items=items, orders=orders,
                           clients=clients, company=COMPANY, user=session,
                           statuses=SRC_STATUSES)


@app.route("/ops/sourcing/new", methods=["POST"])
@login_required
def ops_sourcing_new():
    desc = request.form.get("description", "").strip()
    if not desc:
        flash("Description is required.", "danger")
        return redirect(url_for("ops_sourcing"))
    sid = ops.next_id("SRC", "sourcing", "sourcing_id")
    ops.insert("sourcing", {
        "sourcing_id": sid,
        "src_date": request.form.get("src_date") or datetime.now().strftime("%Y-%m-%d"),
        "order_id": form_order_id(),
        "client_id": request.form.get("client_id", ""),
        "category": request.form.get("category", ""),
        "description": desc,
        "qty": float(request.form.get("qty", 0) or 0),
        "unit": request.form.get("unit", "pcs"),
        "target_price": float(request.form.get("target_price", 0) or 0),
        "supplier_name": request.form.get("supplier_name", ""),
        "supplier_quote": float(request.form.get("supplier_quote", 0) or 0),
        "status": "Request Received",
        "qc_status": "N/A",
        "notes": request.form.get("notes", ""),
    })
    flash(f"Sourcing request {sid} created.", "success")
    return redirect(url_for("ops_sourcing"))


@app.route("/ops/sourcing/<sourcing_id>/status", methods=["POST"])
@login_required
@ops_status_required
def ops_sourcing_status(sourcing_id):
    item = ops.get_one("sourcing", "sourcing_id", sourcing_id)
    if not item:
        flash("Not found.", "danger")
        return redirect(url_for("ops_sourcing"))
    ops.update("sourcing", "sourcing_id", sourcing_id, {
        "status": request.form.get("status", item["status"]),
        "qc_status": request.form.get("qc_status", item.get("qc_status") or "N/A"),
        "supplier_name": request.form.get("supplier_name", item.get("supplier_name") or ""),
        "supplier_quote": float(request.form.get("supplier_quote") or item.get("supplier_quote") or 0),
        "notes": request.form.get("notes", item.get("notes") or ""),
    })
    flash("Sourcing request updated.", "success")
    return redirect(url_for("ops_sourcing"))


# ──────────────────────────────────────────────────────────────


# ── Expenses (office, ops, salaries, day-to-day) ─────────────
@app.route("/ops/expenses", methods=["GET", "POST"])
@login_required
@finance_required
def ops_expenses():
    """Record and list business expenses, wages, and operational costs."""
    users = list_users()
    if request.method == "POST":
        try:
            amount = float(request.form.get("amount", 0) or 0)
            amount_usd = float(request.form.get("amount_usd", 0) or 0)
            currency = (request.form.get("currency") or "GHS").strip().upper()
            # Live FX: never treat GHS amount as USD 1:1
            if amount_usd <= 0 or (currency != "USD" and abs(amount_usd - amount) < 0.0001):
                amount_usd = ops.to_usd(amount, currency)
            elif currency == "USD":
                amount_usd = amount if amount_usd <= 0 else amount_usd
            account = (request.form.get("account") or "").strip()
            status = request.form.get("status") or "Paid"
            eid = ops.add_expense({
                "expense_date": request.form.get("expense_date") or datetime.now().strftime("%Y-%m-%d"),
                "category": request.form.get("category") or "Miscellaneous",
                "subcategory": (request.form.get("subcategory") or "").strip(),
                "description": (request.form.get("description") or "").strip(),
                "payee": (request.form.get("payee") or "").strip(),
                "worker_username": (request.form.get("worker_username") or "").strip(),
                "amount": amount,
                "currency": currency,
                "amount_usd": amount_usd,
                "payment_method": request.form.get("payment_method") or "Cash",
                "reference": (request.form.get("reference") or "").strip(),
                "status": status,
                "recorded_by": session.get("name") or session.get("username"),
                "notes": (request.form.get("notes") or "").strip(),
                "account": account,
            })
            if status == "Paid" and account:
                new_bal = adjust_wallet(account, -amount, currency)
                flash(
                    f"Expense {eid} recorded. {account} balance now "
                    f"{currency} {new_bal if new_bal is not None else '?'}.",
                    "success",
                )
            else:
                flash(f"Expense {eid} recorded.", "success")
        except Exception as e:
            flash(f"Could not save expense: {e}", "danger")
        return redirect(url_for("ops_expenses"))

    month = request.args.get("month") or datetime.now().strftime("%Y-%m")
    expenses = ops.list_expenses()
    if month:
        expenses_view = [e for e in expenses if (e.get("expense_date") or "").startswith(month)]
    else:
        expenses_view = expenses
    summary = ops.expense_summary(month)
    currencies = ["GHS", "USD", "EUR", "GBP", "CNY", "NGN"]
    try:
        from invoice_generator import COMPANY as _c
        # optional: extend from ops if CURRENCIES exists
    except Exception:
        pass
    ra = load_receiving_accounts()
    return render_template(
        "ops_expenses.html",
        expenses=expenses_view,
        all_count=len(expenses),
        summary=summary,
        month=month,
        categories=ops.EXPENSE_CATEGORIES,
        methods=ops.EXPENSE_METHODS,
        currencies=currencies,
        users=users,
        accounts=ACCOUNT_OPTIONS,
        wallets=ra.get("wallets") or {},
        orders=ops.order_list()[:200],
        clients=ops.client_list(),
        company=COMPANY,
        user=session,
    )


@app.route("/ops/expenses/<expense_id>/delete", methods=["POST"])
@login_required
@manage_required
def ops_expense_delete(expense_id):
    row = ops.get_one("expenses", "expense_id", expense_id)
    if not row:
        flash("Expense not found.", "danger")
        return redirect(url_for("ops_expenses"))
    acc, delta = wallet_effect_expense(row)
    if acc and delta:
        adjust_wallet(acc, -delta, row.get("currency"))  # reverse
    ops.delete("expenses", "expense_id", expense_id)
    flash(f"Expense {expense_id} deleted.", "success")
    return redirect(url_for("ops_expenses"))


@app.route("/ops/expenses/<expense_id>/edit", methods=["GET", "POST"])
@login_required
@manage_required
def ops_expense_edit(expense_id):
    row = ops.get_one("expenses", "expense_id", expense_id)
    if not row:
        flash("Expense not found.", "danger")
        return redirect(url_for("ops_expenses"))
    if request.method == "POST":
        old_effect = wallet_effect_expense(row)
        try:
            amount = float(request.form.get("amount", 0) or 0)
            amount_usd = float(request.form.get("amount_usd", 0) or 0)
        except Exception:
            amount, amount_usd = 0.0, 0.0
        currency = (request.form.get("currency") or row.get("currency") or "GHS").strip().upper()
        if currency == "USD" and amount_usd <= 0:
            amount_usd = amount
        account = (request.form.get("account") or "").strip()
        status = request.form.get("status") or "Paid"
        updated = {
            "expense_date": request.form.get("expense_date") or row.get("expense_date"),
            "category": request.form.get("category") or row.get("category"),
            "subcategory": (request.form.get("subcategory") or "").strip(),
            "description": (request.form.get("description") or "").strip(),
            "payee": (request.form.get("payee") or "").strip(),
            "worker_username": (request.form.get("worker_username") or "").strip(),
            "amount": amount,
            "currency": currency,
            "amount_usd": amount_usd,
            "payment_method": request.form.get("payment_method") or row.get("payment_method"),
            "reference": (request.form.get("reference") or "").strip(),
            "status": status,
            "notes": (request.form.get("notes") or "").strip(),
            "account": account,
        }
        ops.update("expenses", "expense_id", expense_id, updated)
        new_row = dict(row)
        new_row.update(updated)
        reapply_wallet(old_effect, wallet_effect_expense(new_row), currency)
        flash(f"Expense {expense_id} updated.", "success")
        return redirect(url_for("ops_expenses"))
    ra = load_receiving_accounts()
    return render_template(
        "ops_expense_edit.html",
        e=row,
        categories=ops.EXPENSE_CATEGORIES,
        methods=ops.EXPENSE_METHODS,
        currencies=["GHS", "USD", "EUR", "GBP", "CNY", "NGN"],
        accounts=ACCOUNT_OPTIONS,
        wallets=ra.get("wallets") or {},
        users=list_users(),
        company=COMPANY,
        user=session,
    )


@app.route("/ops/expenses/<expense_id>/status", methods=["POST"])
@login_required
@finance_required
def ops_expense_status(expense_id):
    row = ops.get_one("expenses", "expense_id", expense_id)
    if not row:
        flash("Expense not found.", "danger")
        return redirect(url_for("ops_expenses"))
    st = request.form.get("status") or row.get("status")
    old_effect = wallet_effect_expense(row)
    ops.update("expenses", "expense_id", expense_id, {"status": st})
    new_row = dict(row)
    new_row["status"] = st
    reapply_wallet(old_effect, wallet_effect_expense(new_row), row.get("currency"))
    flash(f"Expense {expense_id} marked {st}.", "success")
    return redirect(url_for("ops_expenses"))




# ── Income (fees, commissions, service revenue) ───────────────
@app.route("/ops/incomes", methods=["GET", "POST"])
@login_required
@finance_required
def ops_incomes():
    """Record business income: freight fees, commissions, FX margin, etc."""
    if request.method == "POST":
        try:
            amount = float(request.form.get("amount", 0) or 0)
            amount_usd = float(request.form.get("amount_usd", 0) or 0)
            currency = (request.form.get("currency") or "GHS").strip().upper()
            if amount_usd <= 0 or (currency != "USD" and abs(amount_usd - amount) < 0.0001):
                amount_usd = ops.to_usd(amount, currency)
            elif currency == "USD":
                amount_usd = amount if amount_usd <= 0 else amount_usd
            account = (request.form.get("account") or "").strip()
            status = request.form.get("status") or "Received"
            iid = ops.add_income({
                "income_date": request.form.get("income_date") or datetime.now().strftime("%Y-%m-%d"),
                "category": request.form.get("category") or "Other Operating Income",
                "subcategory": (request.form.get("subcategory") or "").strip(),
                "description": (request.form.get("description") or "").strip(),
                "client_name": (request.form.get("client_name") or "").strip(),
                "order_id": (request.form.get("order_id") or "").strip(),
                "amount": amount,
                "currency": currency,
                "amount_usd": amount_usd,
                "payment_method": request.form.get("payment_method") or "Bank Transfer",
                "reference": (request.form.get("reference") or "").strip(),
                "status": status,
                "recorded_by": session.get("name") or session.get("username"),
                "notes": (request.form.get("notes") or "").strip(),
                "account": account,
            })
            if status in ("Received", "Cleared") and account:
                adjust_wallet(account, amount, currency)
                flash(f"Income {iid} recorded and added to {account}.", "success")
            else:
                flash(f"Income {iid} recorded.", "success")
        except Exception as e:
            flash(f"Could not save income: {e}", "danger")
        return redirect(url_for("ops_incomes"))

    month = request.args.get("month") or datetime.now().strftime("%Y-%m")
    incomes = ops.list_incomes()
    incomes_view = [i for i in incomes if (i.get("income_date") or "").startswith(month)] if month else incomes
    summary = ops.income_summary(month)
    pnl = ops.pnl_summary(month)
    orders = ops.order_list()[:100] if hasattr(ops, "order_list") else []
    currencies = ["GHS", "USD", "EUR", "GBP", "CNY", "NGN"]
    ra = load_receiving_accounts()
    return render_template(
        "ops_incomes.html",
        incomes=incomes_view,
        all_count=len(incomes),
        summary=summary,
        pnl=pnl,
        month=month,
        categories=ops.INCOME_CATEGORIES,
        methods=ops.INCOME_METHODS,
        currencies=currencies,
        orders=orders,
        accounts=ACCOUNT_OPTIONS,
        wallets=ra.get("wallets") or {},
        company=COMPANY,
        user=session,
    )


@app.route("/ops/incomes/<income_id>/delete", methods=["POST"])
@login_required
@manage_required
def ops_income_delete(income_id):
    row = ops.get_one("incomes", "income_id", income_id)
    if not row:
        flash("Income not found.", "danger")
        return redirect(url_for("ops_incomes"))
    acc, delta = wallet_effect_income(row)
    if acc and delta:
        adjust_wallet(acc, -delta, row.get("currency"))
    ops.delete("incomes", "income_id", income_id)
    flash(f"Income {income_id} deleted.", "success")
    return redirect(url_for("ops_incomes"))


@app.route("/ops/incomes/<income_id>/edit", methods=["GET", "POST"])
@login_required
@manage_required
def ops_income_edit(income_id):
    row = ops.get_one("incomes", "income_id", income_id)
    if not row:
        flash("Income not found.", "danger")
        return redirect(url_for("ops_incomes"))
    if request.method == "POST":
        old_effect = wallet_effect_income(row)
        try:
            amount = float(request.form.get("amount", 0) or 0)
            amount_usd = float(request.form.get("amount_usd", 0) or 0)
        except Exception:
            amount, amount_usd = 0.0, 0.0
        currency = (request.form.get("currency") or row.get("currency") or "GHS").strip().upper()
        if currency == "USD" and amount_usd <= 0:
            amount_usd = amount
        account = (request.form.get("account") or "").strip()
        status = request.form.get("status") or "Received"
        updated = {
            "income_date": request.form.get("income_date") or row.get("income_date"),
            "category": request.form.get("category") or row.get("category"),
            "subcategory": (request.form.get("subcategory") or "").strip(),
            "description": (request.form.get("description") or "").strip(),
            "client_name": (request.form.get("client_name") or "").strip(),
            "order_id": (request.form.get("order_id") or "").strip(),
            "amount": amount,
            "currency": currency,
            "amount_usd": amount_usd,
            "payment_method": request.form.get("payment_method") or row.get("payment_method"),
            "reference": (request.form.get("reference") or "").strip(),
            "status": status,
            "notes": (request.form.get("notes") or "").strip(),
            "account": account,
        }
        ops.update("incomes", "income_id", income_id, updated)
        new_row = dict(row)
        new_row.update(updated)
        reapply_wallet(old_effect, wallet_effect_income(new_row), currency)
        flash(f"Income {income_id} updated.", "success")
        return redirect(url_for("ops_incomes"))
    ra = load_receiving_accounts()
    orders = ops.order_list()[:100] if hasattr(ops, "order_list") else []
    return render_template(
        "ops_income_edit.html",
        i=row,
        categories=ops.INCOME_CATEGORIES,
        methods=ops.INCOME_METHODS,
        currencies=["GHS", "USD", "EUR", "GBP", "CNY", "NGN"],
        accounts=ACCOUNT_OPTIONS,
        wallets=ra.get("wallets") or {},
        orders=orders,
        company=COMPANY,
        user=session,
    )


@app.route("/ops/incomes/<income_id>/status", methods=["POST"])
@login_required
@finance_required
def ops_income_status(income_id):
    row = ops.get_one("incomes", "income_id", income_id)
    if not row:
        flash("Income not found.", "danger")
        return redirect(url_for("ops_incomes"))
    st = request.form.get("status") or row.get("status")
    old_effect = wallet_effect_income(row)
    ops.update("incomes", "income_id", income_id, {"status": st})
    new_row = dict(row)
    new_row["status"] = st
    reapply_wallet(old_effect, wallet_effect_income(new_row), row.get("currency"))
    flash(f"Income {income_id} marked {st}.", "success")
    return redirect(url_for("ops_incomes"))




# ── Financial Report (period P&L + PDF) ───────────────────────
@app.route("/reports/financial")
@login_required
@finance_required
def financial_report():
    period = request.args.get("period") or "month"
    start = request.args.get("start") or ""
    end = request.args.get("end") or ""
    start_d, end_d, label = period_date_range(period, start or None, end or None)
    summary = ops.financial_summary(start_d, end_d)
    ra = load_receiving_accounts()
    # Invoice slice for period
    db = load_db()
    invs = []
    inv_total = inv_paid = inv_outstanding = 0.0
    for no, inv in (db.get("invoices") or {}).items():
        d = (inv.get("invoice_date") or inv.get("created_at") or "")[:10]
        if d and start_d <= d <= end_d:
            invs.append((no, inv))
            inv_total += float(inv.get("total") or 0)
            inv_paid += float(inv.get("paid") or 0)
            inv_outstanding += max(0.0, float(inv.get("balance_due") or 0))
    invs.sort(key=lambda x: x[1].get("invoice_date") or "", reverse=True)
    return render_template(
        "financial_report.html",
        summary=summary,
        period=period,
        period_label=label,
        start=start_d,
        end=end_d,
        wallets=ra.get("wallets") or {},
        invoices=invs[:50],
        inv_total=inv_total,
        inv_paid=inv_paid,
        inv_outstanding=inv_outstanding,
        company=COMPANY,
        user=session,
    )


@app.route("/reports/financial/pdf")
@login_required
@finance_required
def financial_report_pdf():
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
    from io import BytesIO

    period = request.args.get("period") or "month"
    start = request.args.get("start") or ""
    end = request.args.get("end") or ""
    start_d, end_d, label = period_date_range(period, start or None, end or None)
    s = ops.financial_summary(start_d, end_d)
    ra = load_receiving_accounts()
    wallets = ra.get("wallets") or {}

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16*mm, rightMargin=16*mm, topMargin=14*mm, bottomMargin=14*mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H1", fontSize=16, textColor=colors.HexColor("#0A2540"), spaceAfter=6, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="H2", fontSize=11, textColor=colors.HexColor("#0077B6"), spaceBefore=10, spaceAfter=4, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="Body", fontSize=9, textColor=colors.HexColor("#1A1A2E"), leading=12))
    styles.add(ParagraphStyle(name="Muted", fontSize=8, textColor=colors.HexColor("#5A6A7A")))
    styles.add(ParagraphStyle(name="Right", fontSize=9, alignment=TA_RIGHT))

    story = []
    story.append(Paragraph("WaveTies Logistics — Financial Report", styles["H1"]))
    story.append(Paragraph(f"Period: <b>{label}</b> &nbsp; ({start_d} → {end_d})", styles["Body"]))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["Muted"]))
    story.append(Spacer(1, 8))

    # Summary KPIs
    story.append(Paragraph("Summary (USD equivalent)", styles["H2"]))
    kpi = [
        ["Income received", f"${s['income_received_usd']:,.2f}"],
        ["Income pending", f"${s['income_pending_usd']:,.2f}"],
        ["Expenses paid", f"${s['expense_paid_usd']:,.2f}"],
        ["Expenses pending", f"${s['expense_pending_usd']:,.2f}"],
        ["Net (received − paid)", f"${s['net_usd']:,.2f}"],
    ]
    t = Table(kpi, colWidths=[110*mm, 60*mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E8F4FC")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#CCDDEE")),
    ]))
    story.append(t)

    # Account balances
    story.append(Paragraph("Account balances", styles["H2"]))
    wrows = [["Account", "Currency", "Balance"]]
    for key in ("cash", "momo", "bank"):
        w = wallets.get(key) or {}
        wrows.append([w.get("label") or key, w.get("currency") or "GHS", f"{float(w.get('balance') or 0):,.2f}"])
    wt = Table(wrows, colWidths=[80*mm, 40*mm, 50*mm])
    wt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0A2540")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (2, 1), (2, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CCDDEE")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(wt)

    def cat_table(title, rows):
        story.append(Paragraph(title, styles["H2"]))
        data = [["Category", "Count", "USD Total"]]
        if not rows:
            data.append(["— none —", "0", "$0.00"])
        else:
            for r in rows:
                data.append([r["category"], str(r["n"]), f"${r['total_usd']:,.2f}"])
        tbl = Table(data, colWidths=[100*mm, 30*mm, 40*mm])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0077B6")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CCDDEE")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(tbl)

    cat_table("Income by category (received)", s["income_by_category"])
    cat_table("Expenses by category (paid)", s["expense_by_category"])

    # Line items (cap)
    story.append(Paragraph("Income transactions", styles["H2"]))
    idata = [["Date", "Category", "Description", "Account", "Amount", "USD"]]
    for i in (s["incomes"] or [])[:40]:
        idata.append([
            i.get("income_date") or "",
            (i.get("category") or "")[:22],
            (i.get("description") or "")[:28],
            i.get("account") or "—",
            f"{i.get('currency','')} {float(i.get('amount') or 0):,.2f}",
            f"${float(i.get('amount_usd') or 0):,.2f}",
        ])
    if len(idata) == 1:
        idata.append(["—", "", "No income in period", "", "", ""])
    it = Table(idata, colWidths=[22*mm, 35*mm, 45*mm, 20*mm, 28*mm, 22*mm])
    it.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0A2540")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDD")),
        ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
    ]))
    story.append(it)

    story.append(Paragraph("Expense transactions", styles["H2"]))
    edata = [["Date", "Category", "Description", "Account", "Amount", "USD"]]
    for e in (s["expenses"] or [])[:40]:
        edata.append([
            e.get("expense_date") or "",
            (e.get("category") or "")[:22],
            (e.get("description") or "")[:28],
            e.get("account") or "—",
            f"{e.get('currency','')} {float(e.get('amount') or 0):,.2f}",
            f"${float(e.get('amount_usd') or 0):,.2f}",
        ])
    if len(edata) == 1:
        edata.append(["—", "", "No expenses in period", "", "", ""])
    et = Table(edata, colWidths=[22*mm, 35*mm, 45*mm, 20*mm, 28*mm, 22*mm])
    et.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0A2540")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDD")),
        ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
    ]))
    story.append(et)

    story.append(Spacer(1, 12))
    story.append(Paragraph("WaveTies Logistics And Supply Chain Solutions · Stronger Ties", styles["Muted"]))
    doc.build(story)
    buf.seek(0)
    fname = f"WaveTies_Financial_{start_d}_to_{end_d}.pdf"
    return send_file(buf, as_attachment=True, download_name=fname, mimetype="application/pdf")


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    port = int(os.environ.get("PORT", 5000))
    print("=" * 50)
    print("  WaveTies Operations + Invoice System")
    print(f"  http://127.0.0.1:{port}")
    print("=" * 50)
    print("  Default logins (change after first login):")
    print("    admin  / admin123")
    print("    worker / worker123")
    print("    kofi   / kofi123")
    print("=" * 50)
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "1") == "1")
