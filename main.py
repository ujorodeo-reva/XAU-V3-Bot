import os, time, threading, requests, yfinance as yf, pandas as pd
from flask import Flask
from datetime import datetime

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYMBOL = "GC=F"
RSI_PERIOD = 14
VOL_MULT = 1.25
SCAN_SECONDS = 60

last_state = {"rsi":0,"vol":0,"price":0,"status":"starting"}
last_update = "never"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def rsi_calc(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss.replace(0,0.00001)
    return 100 - (100/(1+rs))

def send_telegram(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      data={"chat_id":CHAT_ID,"text":text,"parse_mode":"Markdown"}, timeout=15)
        log(f"Telegram sent: {text[:60]}")
    except Exception as e:
        log(f"TG error: {e}")

def fetch():
    try:
        df = yf.download(SYMBOL, period="2d", interval="15m", progress=False, auto_adjust=True)
        if df.empty or len(df) < 30:
            log("fetch empty")
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df["rsi"] = rsi_calc(df["Close"], RSI_PERIOD)
        df["vol_ma20"] = df["Volume"].rolling(20).mean()
        return df
    except Exception as e:
        log(f"fetch error: {e}")
        return None

def check_loop():
    global last_state, last_update
    log("Bot started... scanning XAU")
    time.sleep(5)
    while True:
        df = fetch()
        if df is None:
            last_state["status"] = "waiting data"
            time.sleep(30)
            continue
        last = df.iloc[-1]
        prev = df.iloc[-2]
        price = float(last["Close"])
        rsi = float(last["rsi"])
        vol = float(last["Volume"])
        vol_ma = float(last["vol_ma20"])
        vol_ratio = vol / vol_ma if vol_ma>0 else 0
        
        last_state = {"rsi":round(rsi,2),"vol":round(vol_ratio,2),"price":round(price,2),"status":"running"}
        last_update = datetime.now().strftime("%H:%M:%S")
        log(f"{price:.2f} RSI:{rsi:.1f} Vol:{vol_ratio:.2f}x")
        
        # Signal logic here (add your own)
        time.sleep(SCAN_SECONDS)

def telegram_loop():
    log("Telegram listener started")
    offset = 0
    while True:
        try:
            r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                             params={"timeout":20,"offset":offset}, timeout=30).json()
            for upd in r.get("result",[]):
                offset = upd["update_id"]+1
                msg = upd.get("message",{}).get("text","")
                if "/status" in msg:
                    s = last_state
                    send_telegram(f"✅ *XAU V3 LIVE*\nPrice: {s['price']}\nRSI: {s['rsi']}\nVol: {s['vol']}x\nStatus: {s['status']}\nLast: {last_update}")
                if "/checknow" in msg:
                    send_telegram(f"🔍 Checking now...\nPrice {last_state['price']} RSI {last_state['rsi']}")
        except Exception as e:
            log(f"listener error: {e}")
            time.sleep(5)

app = Flask(__name__)
@app.route("/")
def home():
    return f"XAU V3 OK - {last_state} - Last {last_update}"

# START THREADS
threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000, use_reloader=False), daemon=True).start()
threading.Thread(target=telegram_loop, daemon=True).start()

# MAIN LOOP (must be last)
check_loop()
