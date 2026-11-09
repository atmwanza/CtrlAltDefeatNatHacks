"""Entry point for the demo: Adam's spiral backend (app.py, unchanged), the finger-tapping
routes (tapping.py) and the balance test (balance/backend/balance/ + balance/frontend/).

    python -m uvicorn server:app --app-dir 01 --port 5000
"""
import sys
from pathlib import Path

from fastapi.staticfiles import StaticFiles

from app import app          # spiral: /, /analyze, /static, /debug/csv
import tapping               # tapping: /health, /pi/hello, /tapping/*

BALANCE = Path(__file__).resolve().parent.parent / 'balance'
sys.path.insert(0, str(BALANCE / 'backend' / 'balance'))
import balance_api           # balance: /balance/*  (Brahm's sway code + pose bridge)

app.include_router(tapping.router)
app.include_router(balance_api.router)
tapping.UPLOAD_HANDLERS[balance_api.HAND_PREFIX] = balance_api.handle_upload   # Pi clips for balance
app.mount('/balance/static', StaticFiles(directory=BALANCE / 'frontend'), name='balance-static')