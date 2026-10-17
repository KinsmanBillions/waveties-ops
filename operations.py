"""
WaveTies Operations DB — Orders, Payments, Shipments, RMB, Sourcing
Shares the same data/ folder as the invoice system.
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parent
try:
    from paths_config import DATA_DIR as _DATA
except Exception:
    _DATA = ROOT / "data"
    _DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = _DATA / "operations.db"


@contextmanager
def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_ops_db():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            client_id TEXT PRIMARY KEY,
            date_registered TEXT,
            company_name TEXT NOT NULL,
            contact_person TEXT,
            phone TEXT,
            email TEXT,
            country TEXT,
            city TEXT,
            client_type TEXT,
            preferred_currency TEXT DEFAULT 'USD',
            credit_terms INTEGER DEFAULT 0,
            status TEXT DEFAULT 'Active',
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            order_date TEXT,
            client_id TEXT,
            service_type TEXT,
            description TEXT,
            origin TEXT,
            destination TEXT,
            incoterm TEXT,
            currency TEXT DEFAULT 'USD',
            order_value REAL DEFAULT 0,
            status TEXT DEFAULT 'Inquiry',
            payment_status TEXT DEFAULT 'Unpaid',
            value_usd REAL DEFAULT 0,
            assigned_to TEXT,
            expected_delivery TEXT,
            last_updated TEXT,
            invoice_no TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            payment_id TEXT PRIMARY KEY,
            pay_date TEXT,
            order_id TEXT,
            client_id TEXT,
            pay_type TEXT,
            direction TEXT,
            currency TEXT,
            amount REAL DEFAULT 0,
            amount_usd REAL DEFAULT 0,
            method TEXT,
            reference TEXT,
            bank_channel TEXT,
            recorded_by TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS shipments (
            shipment_id TEXT PRIMARY KEY,
            order_id TEXT,
            client_id TEXT,
            mode TEXT,
            carrier TEXT,
            bl_awb TEXT,
            container_tracking TEXT,
            origin_port TEXT,
            dest_port TEXT,
            etd TEXT, eta TEXT, atd TEXT, ata TEXT,
            status TEXT DEFAULT 'Booked',
            weight_kg REAL, cbm REAL,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS rmb_txns (
            txn_id TEXT PRIMARY KEY,
            txn_date TEXT,
            order_id TEXT,
            client_id TEXT,
            txn_type TEXT,
            cny_amount REAL DEFAULT 0,
            usd_amount REAL DEFAULT 0,
            rate_used REAL DEFAULT 7.14,
            direction TEXT,
            counterparty TEXT,
            channel TEXT,
            status TEXT DEFAULT 'Pending',
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS sourcing (
            sourcing_id TEXT PRIMARY KEY,
            src_date TEXT,
            order_id TEXT,
            client_id TEXT,
            category TEXT,
            description TEXT,
            qty REAL, unit TEXT,
            target_price REAL,
            supplier_name TEXT,
            supplier_quote REAL,
            status TEXT DEFAULT 'Request Received',
            qc_status TEXT DEFAULT 'N/A',
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            expense_id TEXT PRIMARY KEY,
            expense_date TEXT,
            category TEXT NOT NULL,
            subcategory TEXT,
            description TEXT,
            payee TEXT,
            worker_username TEXT,
            amount REAL DEFAULT 0,
            currency TEXT DEFAULT 'GHS',
            amount_usd REAL DEFAULT 0,
            payment_method TEXT,
            reference TEXT,
            status TEXT DEFAULT 'Paid',
            recorded_by TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS incomes (
            income_id TEXT PRIMARY KEY,
            income_date TEXT,
            category TEXT NOT NULL,
            subcategory TEXT,
            description TEXT,
            client_name TEXT,
            order_id TEXT,
            amount REAL DEFAULT 0,
            currency TEXT DEFAULT 'GHS',
            amount_usd REAL DEFAULT 0,
            payment_method TEXT,
            reference TEXT,
            status TEXT DEFAULT 'Received',
            recorded_by TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")

        # Migrations: link to cash accounts
        for tbl, col in (("expenses", "account"), ("incomes", "account")):
            try:
                cols = [r[1] for r in c.execute(f"PRAGMA table_info({tbl})").fetchall()]
                if col not in cols:
                    c.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} TEXT")
            except Exception:
                pass

        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('rmb_rate', '7.14')")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('rmb_rates_json', '{}')")
        # Migration: base currency for multi-currency RMB desk
        cols = [r[1] for r in c.execute("PRAGMA table_info(rmb_txns)").fetchall()]
        if "base_currency" not in cols:
            c.execute("ALTER TABLE rmb_txns ADD COLUMN base_currency TEXT DEFAULT 'USD'")
        if "base_amount" not in cols:
            c.execute("ALTER TABLE rmb_txns ADD COLUMN base_amount REAL DEFAULT 0")

        # Sample data only when explicitly requested (env SAMPLE_SEED=1) and tables empty
        import os
        if os.environ.get("SAMPLE_SEED") == "1":
            if c.execute("SELECT COUNT(*) FROM clients").fetchone()[0] == 0:
                _seed(c)


def _seed(c):
    clients = [
        ("WT-C001", "2025-01-15", "Lagos Trade Hub Ltd", "Adebayo Okonkwo",
         "+234 801 234 5678", "adebayo@lagostrade.ng", "Nigeria", "Lagos",
         "Importer", "USD", 14, "Active", "KYC complete"),
        ("WT-C002", "2025-02-03", "Accra Goods Co.", "Ama Mensah",
         "+233 24 567 8901", "ama@accragoods.gh", "Ghana", "Accra",
         "Importer", "USD", 7, "Active", ""),
        ("WT-C003", "2025-02-20", "Nairobi Imports KE", "James Kamau",
         "+254 712 345 678", "james@nairobiimp.ke", "Kenya", "Nairobi",
         "Distributor", "USD", 21, "Active", "Preferred client"),
    ]
    c.executemany("""INSERT INTO clients
        (client_id, date_registered, company_name, contact_person, phone, email,
         country, city, client_type, preferred_currency, credit_terms, status, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", clients)

    orders = [
        ("WT-ORD-2025-001", "2025-06-12", "WT-C001", "COMBO",
         "Electronics + RMB + Sea freight", "Shenzhen, CN", "Lagos, NG", "CIF",
         "USD", 18500, "In Transit", "Paid", 18500, "Ops Team", "2025-08-05",
         "2025-07-20", "", "Container MSCU1234567"),
        ("WT-ORD-2025-002", "2025-07-01", "WT-C002", "SRC",
         "Sourcing fashion accessories", "Guangzhou, CN", "Accra, GH", "FOB",
         "USD", 4200, "Paid / Processing", "Paid", 4200, "Sourcing Desk",
         "2025-08-15", "2025-07-18", "", ""),
        ("WT-ORD-2025-003", "2025-07-15", "WT-C003", "SHIP",
         "LCL machinery parts", "Ningbo, CN", "Mombasa, KE", "CFR",
         "USD", 9800, "Payment Pending", "Partial", 9800, "Ops Team",
         "2025-09-01", "2025-07-22", "", "Awaiting balance"),
    ]
    c.executemany("""INSERT INTO orders
        (order_id, order_date, client_id, service_type, description, origin, destination,
         incoterm, currency, order_value, status, payment_status, value_usd, assigned_to,
         expected_delivery, last_updated, invoice_no, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", orders)


def next_id(prefix, table, id_col):
    with get_conn() as conn:
        rows = conn.execute(f"SELECT {id_col} FROM {table}").fetchall()
        nums = []
        for r in rows:
            try:
                nums.append(int(r[0].split("-")[-1]))
            except Exception:
                pass
        n = max(nums) + 1 if nums else 1
        year = datetime.now().strftime("%Y")
        if prefix in ("ORD", "PAY", "SHP", "RMB", "SRC"):
            return f"WT-{prefix}-{year}-{n:03d}"
        return f"WT-{prefix}{n:03d}"


def get_all(table, order_by=None):
    with get_conn() as conn:
        q = f"SELECT * FROM {table}"
        if order_by:
            q += f" ORDER BY {order_by}"
        return [dict(r) for r in conn.execute(q).fetchall()]


def get_one(table, id_col, id_val):
    with get_conn() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE {id_col}=?", (id_val,)).fetchone()
        return dict(row) if row else None


def insert(table, data: dict):
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    with get_conn() as conn:
        conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", list(data.values()))


def delete(table, id_col, id_val):
    with get_conn() as conn:
        conn.execute(f"DELETE FROM {table} WHERE {id_col}=?", (id_val,))


def update(table, id_col, id_val, data: dict):
    sets = ", ".join([f"{k}=?" for k in data.keys()])
    with get_conn() as conn:
        conn.execute(f"UPDATE {table} SET {sets} WHERE {id_col}=?", list(data.values()) + [id_val])


def get_setting(key, default=""):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key, value):
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(value)))


def client_list():
    return get_all("clients", order_by="company_name")


def order_list():
    return get_all("orders", order_by="order_date DESC")


def ops_kpis():
    with get_conn() as conn:
        active = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE status NOT IN ('Closed','Cancelled')"
        ).fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE status='Payment Pending'"
        ).fetchone()[0]
        transit = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE status='In Transit'"
        ).fetchone()[0]
        rev = conn.execute(
            "SELECT COALESCE(SUM(value_usd),0) FROM orders WHERE status!='Cancelled'"
        ).fetchone()[0]
        recv = conn.execute(
            "SELECT COALESCE(SUM(value_usd),0) FROM orders WHERE status IN ('Payment Pending','Confirmed')"
        ).fetchone()[0]
        pin = conn.execute(
            "SELECT COALESCE(SUM(amount_usd),0) FROM payments WHERE direction='IN'"
        ).fetchone()[0]
        pout = conn.execute(
            "SELECT COALESCE(SUM(amount_usd),0) FROM payments WHERE direction='OUT'"
        ).fetchone()[0]
        clients = conn.execute(
            "SELECT COUNT(*) FROM clients WHERE status='Active'"
        ).fetchone()[0]
        return {
            "active_orders": active, "pending_pay": pending, "in_transit": transit,
            "total_rev": rev, "receivables": recv, "total_in": pin, "total_out": pout,
            "net": pin - pout, "active_clients": clients,
        }


def get_rmb_rates():
    """Return dict of base_currency -> CNY per 1 unit of base currency."""
    import json
    raw = get_setting("rmb_rates_json", "{}")
    try:
        rates = json.loads(raw) if raw else {}
    except Exception:
        rates = {}
    # Seed USD from legacy single rate if missing
    if "USD" not in rates:
        try:
            rates["USD"] = float(get_setting("rmb_rate", "7.14"))
        except Exception:
            rates["USD"] = 7.14
    return rates


def set_rmb_rate_for(currency, rate):
    import json
    rates = get_rmb_rates()
    rates[currency] = float(rate)
    set_setting("rmb_rates_json", json.dumps(rates))
    if currency == "USD":
        set_setting("rmb_rate", str(rate))


# ── Expenses ──────────────────────────────────────────────────
EXPENSE_CATEGORIES = [
    "Salaries & Wages",
    "Office Rent",
    "Utilities",
    "Internet & Phone",
    "Office Supplies",
    "Transport & Fuel",
    "Marketing & Ads",
    "Software & Subscriptions",
    "Bank Charges",
    "Professional Fees",
    "Repairs & Maintenance",
    "Staff Welfare",
    "Customs & Clearing (ops)",
    "Warehouse & Storage",
    "Miscellaneous",
]

EXPENSE_METHODS = [
    "Cash", "MTN MoMo", "Telecel Cash", "Bank Transfer", "Cheque", "Card", "Other"
]


def next_expense_id():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT expense_id FROM expenses ORDER BY expense_id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return "EXP-0001"
    try:
        n = int(str(row["expense_id"]).split("-")[-1])
        return f"EXP-{n+1:04d}"
    except Exception:
        return f"EXP-{int(__import__('time').time()) % 10000:04d}"


def list_expenses(limit=500):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM expenses ORDER BY expense_date DESC, created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_expense(data: dict):
    eid = data.get("expense_id") or next_expense_id()
    data = dict(data)
    data["expense_id"] = eid
    cols = [
        "expense_id", "expense_date", "category", "subcategory", "description",
        "payee", "worker_username", "amount", "currency", "amount_usd",
        "payment_method", "reference", "status", "recorded_by", "notes", "account",
    ]
    vals = [data.get(c) for c in cols]
    with get_conn() as conn:
        conn.execute(
            f"INSERT INTO expenses ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            vals,
        )
    return eid


def expense_summary(month=None):
    """Return totals by category and overall. month: 'YYYY-MM' or None for all."""
    with get_conn() as conn:
        if month:
            rows = conn.execute(
                "SELECT category, currency, SUM(amount) as total, SUM(amount_usd) as total_usd, COUNT(*) as n "
                "FROM expenses WHERE expense_date LIKE ? GROUP BY category, currency",
                (f"{month}%",),
            ).fetchall()
            paid = conn.execute(
                "SELECT SUM(amount_usd) FROM expenses WHERE status='Paid' AND expense_date LIKE ?",
                (f"{month}%",),
            ).fetchone()[0] or 0
            pending = conn.execute(
                "SELECT SUM(amount_usd) FROM expenses WHERE status!='Paid' AND expense_date LIKE ?",
                (f"{month}%",),
            ).fetchone()[0] or 0
        else:
            rows = conn.execute(
                "SELECT category, currency, SUM(amount) as total, SUM(amount_usd) as total_usd, COUNT(*) as n "
                "FROM expenses GROUP BY category, currency"
            ).fetchall()
            paid = conn.execute(
                "SELECT SUM(amount_usd) FROM expenses WHERE status='Paid'"
            ).fetchone()[0] or 0
            pending = conn.execute(
                "SELECT SUM(amount_usd) FROM expenses WHERE status!='Paid'"
            ).fetchone()[0] or 0
    return {
        "by_category": [dict(r) for r in rows],
        "paid_usd": float(paid),
        "pending_usd": float(pending),
        "total_usd": float(paid) + float(pending),
    }


# ── Income ───────────────────────────────────────────────────
INCOME_CATEGORIES = [
    "Invoice Payment",
    "Freight & Shipping Fees",
    "Sourcing / Buy-for-Me Commission",
    "RMB / FX Margin",
    "Documentation & Handling",
    "Customs Support Fees",
    "Warehouse & Storage",
    "Packing & Insurance",
    "Consultation & Agency",
    "Client Service Charge",
    "Other Operating Income",
]

INCOME_METHODS = [
    "Cash", "MTN MoMo", "Telecel Cash", "Bank Transfer", "Cheque", "Card", "Other"
]


def next_income_id():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT income_id FROM incomes ORDER BY income_id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return "INC-0001"
    try:
        n = int(str(row["income_id"]).split("-")[-1])
        return f"INC-{n+1:04d}"
    except Exception:
        return f"INC-{int(__import__('time').time()) % 10000:04d}"


def list_incomes(limit=500):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM incomes ORDER BY income_date DESC, created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_income(data: dict):
    iid = data.get("income_id") or next_income_id()
    data = dict(data)
    data["income_id"] = iid
    cols = [
        "income_id", "income_date", "category", "subcategory", "description",
        "client_name", "order_id", "amount", "currency", "amount_usd",
        "payment_method", "reference", "status", "recorded_by", "notes", "account",
    ]
    vals = [data.get(c) for c in cols]
    with get_conn() as conn:
        conn.execute(
            f"INSERT INTO incomes ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            vals,
        )
    return iid


def income_summary(month=None):
    with get_conn() as conn:
        if month:
            rows = conn.execute(
                "SELECT category, currency, SUM(amount) as total, SUM(amount_usd) as total_usd, COUNT(*) as n "
                "FROM incomes WHERE income_date LIKE ? GROUP BY category, currency",
                (f"{month}%",),
            ).fetchall()
            received = conn.execute(
                "SELECT SUM(amount_usd) FROM incomes WHERE status IN ('Received','Cleared') AND income_date LIKE ?",
                (f"{month}%",),
            ).fetchone()[0] or 0
            pending = conn.execute(
                "SELECT SUM(amount_usd) FROM incomes WHERE status NOT IN ('Received','Cleared') AND income_date LIKE ?",
                (f"{month}%",),
            ).fetchone()[0] or 0
        else:
            rows = conn.execute(
                "SELECT category, currency, SUM(amount) as total, SUM(amount_usd) as total_usd, COUNT(*) as n "
                "FROM incomes GROUP BY category, currency"
            ).fetchall()
            received = conn.execute(
                "SELECT SUM(amount_usd) FROM incomes WHERE status IN ('Received','Cleared')"
            ).fetchone()[0] or 0
            pending = conn.execute(
                "SELECT SUM(amount_usd) FROM incomes WHERE status NOT IN ('Received','Cleared')"
            ).fetchone()[0] or 0
    return {
        "by_category": [dict(r) for r in rows],
        "received_usd": float(received),
        "pending_usd": float(pending),
        "total_usd": float(received) + float(pending),
    }


def pnl_summary(month=None):
    """Simple profit snapshot: income received vs expenses paid (USD eq.)."""
    inc = income_summary(month)
    exp = expense_summary(month)
    income = inc.get("received_usd") or 0
    expense = exp.get("paid_usd") or 0
    return {
        "income_usd": income,
        "expense_usd": expense,
        "net_usd": income - expense,
        "income_pending_usd": inc.get("pending_usd") or 0,
        "expense_pending_usd": exp.get("pending_usd") or 0,
        "month": month,
    }


def list_expenses_between(start_date, end_date):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM expenses WHERE expense_date >= ? AND expense_date <= ? "
            "ORDER BY expense_date DESC, created_at DESC",
            (start_date, end_date),
        ).fetchall()
    return [dict(r) for r in rows]


def list_incomes_between(start_date, end_date):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM incomes WHERE income_date >= ? AND income_date <= ? "
            "ORDER BY income_date DESC, created_at DESC",
            (start_date, end_date),
        ).fetchall()
    return [dict(r) for r in rows]


def financial_summary(start_date, end_date):
    """P&L style summary for a date range (inclusive)."""
    expenses = list_expenses_between(start_date, end_date)
    incomes = list_incomes_between(start_date, end_date)
    exp_paid = sum(float(e.get("amount_usd") or 0) for e in expenses if e.get("status") == "Paid")
    exp_pending = sum(float(e.get("amount_usd") or 0) for e in expenses if e.get("status") != "Paid")
    inc_recv = sum(float(i.get("amount_usd") or 0) for i in incomes if i.get("status") in ("Received", "Cleared"))
    inc_pending = sum(float(i.get("amount_usd") or 0) for i in incomes if i.get("status") not in ("Received", "Cleared"))

    def by_cat(rows, status_ok):
        bag = {}
        for r in rows:
            if not status_ok(r.get("status")):
                continue
            cat = r.get("category") or "Other"
            bag.setdefault(cat, {"n": 0, "usd": 0.0})
            bag[cat]["n"] += 1
            bag[cat]["usd"] += float(r.get("amount_usd") or 0)
        return sorted(
            [{"category": k, "n": v["n"], "total_usd": v["usd"]} for k, v in bag.items()],
            key=lambda x: -x["total_usd"],
        )

    return {
        "start": start_date,
        "end": end_date,
        "expenses": expenses,
        "incomes": incomes,
        "expense_paid_usd": exp_paid,
        "expense_pending_usd": exp_pending,
        "income_received_usd": inc_recv,
        "income_pending_usd": inc_pending,
        "net_usd": inc_recv - exp_paid,
        "income_by_category": by_cat(incomes, lambda s: s in ("Received", "Cleared")),
        "expense_by_category": by_cat(expenses, lambda s: s == "Paid"),
    }
