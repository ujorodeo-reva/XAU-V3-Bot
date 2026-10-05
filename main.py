import yfinance as yf
import pandas as pd
import ta
import time
import requests
import os
from datetime import datetime
from flask import Flask
import threading

# --- Flask keep-alive for Render ---
app = Flask(__name__)
@app.route('/')
def home():
    return "XAU V3 5m + S/R Bot LIVE!"
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
threading.Thread(target=run_flask, daemon=True).start()
# ------------------------------------

SYMBOL = "GC=F"
TIMEFRAME = "5m"
SL_PCT = 0.004
TP_PCT = 0.008
VOL_MIN = 1.25
VOL_MAX = 1.70
MAX_DIST_EMA = 0.007
SR_LOOKBACK = 50
SR_PROXIMITY = 0.005

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Global state for /status command
last_state = {
    "price": 0,
    "support": 0,
    "resistance": 0,
    "rsi": 0,
    "vol": 0,
    "ema9": 0,
    "ema20": 0,
    "ema200": 0,
    "near_sup": False,
    "near_res": False,
    "last_update": "Never",
    "status": "Starting..."
}

def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        print("No Telegram creds")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def get_sr_levels(df):
    try:
        recent = df.tail(SR_LOOKBACK)
        support = float(recent['Low'].rolling(10).min().iloc[-1])
        lows = recent.nsmallest(3, 'Low')['Low'].mean()
        highs = recent.nlargest(3, 'High')['High'].mean()
        return float(lows), float(highs)
    except:
        return float(df['Low'].tail(20).min()), float(df['High'].tail(20).max())

def fetch_data():
    for attempt in range(3):
        try:
            df = yf.download(SYMBOL, period="5d", interval=TIMEFRAME, progress=False, auto_adjust=False)
            if df is not None and not df.empty and len(df) > 50:
                df = df.dropna()
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                return df
        except Exception as e:
            print(f"yfinance attempt {attempt+1} failed: {e}")
        time.sleep(5)
    return None

def check_signal():
    df = fetch_data()
    if df is None or len(df) < 250:
        print(f"[{datetime.now()}] No data / too short. Retrying...")
        last_state["status"] = "Waiting for data (Yahoo 429?)"
        return

    df['EMA200'] = ta.trend.ema_indicator(df['Close'], window=200)
    df['EMA9'] = ta.trend.ema_indicator(df['Close'], window=9)
    df['EMA20'] = ta.trend.ema_indicator(df['Close
