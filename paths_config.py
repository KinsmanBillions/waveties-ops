"""
Persistent data directory for WaveTies.

On Render / Railway the container filesystem is ephemeral: every redeploy
wipes local files. Point WAVETIES_DATA at a persistent disk mount so
users, orders, invoices and settings survive restarts.

  Render:  add a disk mounted at /var/data
           env: WAVETIES_DATA=/var/data
  Railway: use a volume, same env var
  Local:   defaults to <app>/data
"""
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

def get_data_dir() -> Path:
    env = (os.environ.get("WAVETIES_DATA") or os.environ.get("DATA_DIR") or "").strip()
    if env:
        p = Path(env)
    else:
        p = _ROOT / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p

DATA_DIR = get_data_dir()
