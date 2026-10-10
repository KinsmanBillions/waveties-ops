"""
WaveTies Operations DB — Orders, Payments, Shipments, RMB, Sourcing
Shares the same data/ folder as the invoice system.
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "operations.db"


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
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('rmb_rate', '7.14')")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('rmb_rates_json', '{}')")
        # Migration: base currency for multi-currency RMB desk
        cols = [r[1] for r in c.execute("PRAGMA table_info(rmb_txns)").fetchall()]
        if "base_currency" not in cols:
            c.execute("ALTER TABLE rmb_txns ADD COLUMN base_currency TEXT DEFAULT 'USD'")
        if "base_amount" not in cols:
            c.execute("ALTER TABLE rmb_txns ADD COLUMN base_amount REAL DEFAULT 0")

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
