"""Entry point for the demo: Adam's spiral backend (app.py, unchanged) plus the
finger-tapping prototype routes (tapping.py).

    python -m uvicorn server:app --app-dir 01 --port 5000
"""
from app import app          # spiral: /, /analyze, /static, /debug/csv
from tapping import router   # tapping: /health, /pi/hello, /tapping/*

app.include_router(router)
