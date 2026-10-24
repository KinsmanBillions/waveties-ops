"""
WaveTies Manager — standalone manual books (NOT linked to main operations).

Entries are typed by hand or loaded from an imported backup.
Reception can export a backup file for the admin to import elsewhere.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

try:
    from paths_config import DATA_DIR as _DATA
except Exception:
    _DATA = Path(__file__).resolve().parent / "data"
    _DATA.mkdir(parents=True, exist_ok=True)

DB_PATH = _DATA / "manager_books.db"


@contextmanager
def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_manager_db():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            account_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            account_type TEXT DEFAULT 'Cash',
            currency TEXT DEFAULT 'GHS',
            opening_balance REAL DEFAULT 0,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            entry_id TEXT PRIMARY KEY,
            entry_date TEXT NOT NULL,
            account_id TEXT,
            direction TEXT DEFAULT 'IN',
            category TEXT,
            description TEXT,
            amount REAL DEFAULT 0,
            currency TEXT DEFAULT 'GHS',
            reference TEXT,
            recorded_by TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")
        # Seed default accounts if empty
        n = c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        if n == 0:
            for aid, name, atype in (
                ("MGR-CASH", "Cash on Hand", "Cash"),
                ("MGR-MOMO", "Mobile Money", "Mobile Money"),
                ("MGR-BANK", "Bank Account", "Bank"),
            ):
                c.execute(
                    "INSERT INTO accounts (account_id, name, account_type, currency, opening_balance) "
                    "VALUES (?,?,?,?,0)",
                    (aid, name, atype, "GHS"),
                )


def _next_id(prefix, table, col):
    with get_conn() as conn:
        rows = conn.execute(f"SELECT {col} FROM {table}").fetchall()
    nums = []
    for r in rows:
        s = str(r[0] or "")
        parts = s.replace(prefix, "").split("-")
        try:
            nums.append(int(parts[-1]))
        except Exception:
            pass
    n = (max(nums) + 1) if nums else 1
    return f"{prefix}{n:04d}"


def list_accounts():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM accounts ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def add_account(data: dict):
    aid = data.get("account_id") or _next_id("MGR-A", "accounts", "account_id")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO accounts (account_id, name, account_type, currency, opening_balance, notes) "
            "VALUES (?,?,?,?,?,?)",
            (
                aid,
                data.get("name") or "Account",
                data.get("account_type") or "Cash",
                data.get("currency") or "GHS",
                float(data.get("opening_balance") or 0),
                data.get("notes") or "",
            ),
        )
    return aid


def list_entries(limit=500):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT e.*, a.name as account_name FROM entries e "
            "LEFT JOIN accounts a ON a.account_id = e.account_id "
            "ORDER BY e.entry_date DESC, e.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_entry(data: dict):
    eid = data.get("entry_id") or _next_id("MGR-E", "entries", "entry_id")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO entries (entry_id, entry_date, account_id, direction, category, "
            "description, amount, currency, reference, recorded_by, notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                eid,
                data.get("entry_date") or datetime.now().strftime("%Y-%m-%d"),
                data.get("account_id") or "",
                (data.get("direction") or "IN").upper(),
                data.get("category") or "",
                data.get("description") or "",
                float(data.get("amount") or 0),
                data.get("currency") or "GHS",
                data.get("reference") or "",
                data.get("recorded_by") or "",
                data.get("notes") or "",
            ),
        )
    return eid


def delete_entry(entry_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM entries WHERE entry_id=?", (entry_id,))


def account_balances():
    """Opening balance ± entries (manual only)."""
    accounts = list_accounts()
    entries = list_entries(limit=10000)
    by_acc = {a["account_id"]: float(a.get("opening_balance") or 0) for a in accounts}
    names = {a["account_id"]: a for a in accounts}
    for e in entries:
        aid = e.get("account_id") or ""
        if aid not in by_acc:
            by_acc[aid] = 0.0
        amt = float(e.get("amount") or 0)
        if (e.get("direction") or "IN").upper() == "OUT":
            by_acc[aid] -= amt
        else:
            by_acc[aid] += amt
    result = []
    for aid, bal in by_acc.items():
        info = names.get(aid) or {"account_id": aid, "name": aid, "currency": "GHS"}
        result.append({
            "account_id": aid,
            "name": info.get("name") or aid,
            "currency": info.get("currency") or "GHS",
            "balance": round(bal, 2),
            "account_type": info.get("account_type") or "",
        })
    return result


def export_backup() -> dict:
    """Full Manager snapshot for export (JSON-serializable)."""
    return {
        "format": "waveties-manager-backup",
        "version": 1,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "accounts": list_accounts(),
        "entries": list_entries(limit=50000),
    }


def import_backup(payload: dict, mode: str = "merge") -> tuple:
    """
    Import a Manager backup.
    mode=merge: upsert accounts/entries by id
    mode=replace: wipe Manager tables then load
    Returns (n_accounts, n_entries)
    """
    if not isinstance(payload, dict):
        raise ValueError("Invalid backup file")
    accounts = payload.get("accounts") or []
    entries = payload.get("entries") or []
    with get_conn() as conn:
        if mode == "replace":
            conn.execute("DELETE FROM entries")
            conn.execute("DELETE FROM accounts")
        for a in accounts:
            aid = a.get("account_id")
            if not aid:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO accounts "
                "(account_id, name, account_type, currency, opening_balance, notes, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    aid,
                    a.get("name") or aid,
                    a.get("account_type") or "Cash",
                    a.get("currency") or "GHS",
                    float(a.get("opening_balance") or 0),
                    a.get("notes") or "",
                    a.get("created_at") or datetime.now().isoformat(timespec="seconds"),
                ),
            )
        for e in entries:
            eid = e.get("entry_id")
            if not eid:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO entries "
                "(entry_id, entry_date, account_id, direction, category, description, "
                "amount, currency, reference, recorded_by, notes, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    eid,
                    e.get("entry_date") or "",
                    e.get("account_id") or "",
                    (e.get("direction") or "IN").upper(),
                    e.get("category") or "",
                    e.get("description") or "",
                    float(e.get("amount") or 0),
                    e.get("currency") or "GHS",
                    e.get("reference") or "",
                    e.get("recorded_by") or "",
                    e.get("notes") or "",
                    e.get("created_at") or datetime.now().isoformat(timespec="seconds"),
                ),
            )
    return len(accounts), len(entries)


def summary():
    entries = list_entries(limit=10000)
    total_in = sum(float(e["amount"] or 0) for e in entries if (e.get("direction") or "").upper() == "IN")
    total_out = sum(float(e["amount"] or 0) for e in entries if (e.get("direction") or "").upper() == "OUT")
    return {
        "entries": len(entries),
        "total_in": round(total_in, 2),
        "total_out": round(total_out, 2),
        "net": round(total_in - total_out, 2),
        "balances": account_balances(),
    }
