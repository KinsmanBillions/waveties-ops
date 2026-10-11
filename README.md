# WaveTies Operations + Invoice System

**Stronger Ties** — Unified online platform for WaveTies Logistics and Supply Chain Limited.

## What's included

| Module | Features |
|--------|----------|
| **Auth** | Admin / Worker roles, hashed passwords |
| **Dashboard** | Invoice + Operations KPIs |
| **Orders** | SHIP, SRC, BFM, RMB, PAY, VAL, COMBO — full lifecycle |
| **Clients** | Client register with KYC notes |
| **Invoices** | Professional PDF (ReportLab), mark paid, email, WhatsApp-ready |
| **Invoice from Order** | One-click generate invoice from any order |
| **Payments** | IN/OUT payment register linked to orders |
| **Shipments** | Cargo tracking (ETD/ETA/ATD/ATA) |
| **RMB Desk** | CNY exchange & supplier payments with live rate |
| **Sourcing** | Buy-for-Me / procurement pipeline + QC |
| **Customers** | Invoice customer book |
| **Reports** | By month, worker, transport mode |
| **Admin** | User management, SMTP email setup |


## Roles & Permissions

| Action | Worker | Admin |
|--------|:------:|:-----:|
| Login & view all data | ✅ | ✅ |
| Create clients, orders, invoices, payments, shipments, RMB, sourcing | ✅ | ✅ |
| Create invoice from order | ✅ | ✅ |
| Download / email PDF | ✅ | ✅ |
| Edit order / shipment / sourcing status | ❌ | ✅ |
| Mark invoice as paid | ❌ | ✅ |
| Edit or delete customers | ❌ | ✅ |
| Change RMB reference rate | ❌ | ✅ |
| Manage users & passwords | ❌ | ✅ |
| Configure SMTP email | ❌ | ✅ |

Workers **create** commercial records. Only admins **edit or delete**.

## Default logins (change immediately)

- `admin` / `admin123`
- `worker` / `worker123`
- `kofi` / `kofi123`

## Deploy FREE

### Railway (recommended)
1. Push this folder to a GitHub repo (files at **root**).
2. [railway.app](https://railway.app) → New Project → Deploy from GitHub.
3. Add env var: `SECRET_KEY` = long random string.
4. Deploy. Uses Procfile automatically.

### Render
1. New Web Service → connect repo.
2. Build: `pip install -r requirements.txt`
3. Start: `gunicorn -b 0.0.0.0:$PORT app:app`
4. Env: `SECRET_KEY`

### Local
```bash
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000

## Brand
Navy `#0A2540` · Sea Blue `#00B4D8` · Tagline: *Stronger Ties*


## Data persistence (important)

On **Render** and **Railway**, the app disk is **ephemeral**. Redeploys wipe local files, so `data/users.db` and orders would reset to defaults unless you attach a **persistent disk**.

### Render setup
1. Dashboard → your service → **Disks** → Add disk  
2. Mount path: `/var/data`  
3. Environment variables:

| Variable | Value | Purpose |
|----------|--------|---------|
| `WAVETIES_DATA` | `/var/data` | Store users, orders, invoices here |
| `SECRET_KEY` | long random string | Keep sessions stable across restarts |
| `WAVETIES_RECOVERY_KEY` | your secret | Admin password recovery |
| `ADMIN_PASSWORD` | (optional) | Used only on **first** boot if DB is empty |
| `SEED_DEMO_USERS` | leave unset | Do **not** set in production |

4. Redeploy once after adding the disk.

Without `WAVETIES_DATA` on a persistent volume, **every redeploy recreates an empty database** and seeds a default `admin` account again.

### What is stored under WAVETIES_DATA
- `users.db` — logins and roles  
- `operations.db` — clients, orders, payments, shipments, RMB, sourcing  
- `invoices_db.json` — invoices  
- `invoices/` — PDF files  
- `smtp_config.json`, `receiving_accounts.json`, `reset_tokens.json`
