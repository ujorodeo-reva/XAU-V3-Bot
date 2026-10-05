import os, time, threading, requests
import pandas as pd
import numpy as np
from flask import Flask

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYMBOL = "PAXGUSDT"

# Two endpoints - if one fails, use the other
BINANCE_URLS = [
    f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval=5m&limit=100",
    f"https://data-api.binance.vision/api/v3/klines?symbol={SYMBOL}&interval=5m&limit=100"
]

app = Flask(__name__)

last_price = 0
last_rsi = 0
last_check = "Never"
active_trade = None

def send_tg(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"SEND FAIL {e}")

def get_klines():
    for url in BINANCE_URLS:
        try:
            r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10).json()
            if isinstance(r, list) and len(r)>0:
                df = pd.DataFrame(r, columns=["t","o","h","l","c","v","ct","q","n","tb","tq","ig"])
                for col in ["o","h","l","c","v"]:
                    df[col] = df[col].astype(float)
                print(f"BINANCE OK from {url[:30]}")
                return df
        except Exception as e:
            print(f"BINANCE FAIL {url} {e}")
    print("ALL BINANCE FAILED")
    return None

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def check_market():
    global last_price, last_rsi, last_check, active_trade
    print("MARKET CHECK THREAD STARTED")
    time.sleep(5) # wait for bot to start
    while True:
        try:
            df = get_klines()
            if df is None or len(df) < 30:
                print("No data, retry in 30s")
                time.sleep(30)
                continue

            df["ema9"] = df["c"].ewm(span=9).mean()
            df["ema21"] = df["c"].ewm(span=21).mean()
            df["ema20"] = df["c"].ewm(span=20).mean()
            df["rsi"] = calc_rsi(df["c"], 14)
            df["vol_ma20"] = df["v"].rolling(20).mean()
            df["roc"] = df["c"].pct_change(3) * 100

            c0 = df.iloc[-1]
            c1 = df.iloc[-2]

            price = float(c0["c"])
            rsi = float(c0["rsi"])
            last_price = price
            last_rsi = rsi
            last_check = time.strftime("%H:%M:%S")
            print(f"CHECK {price:.2f} RSI {rsi:.1f}")

            # Track active trade
            if active_trade:
                entry = active_trade["entry"]
                if active_trade["dir"] == "BUY":
                    if price >= active_trade["tp"]:
                        send_tg(f"✅ <b>TP HIT BUY</b>\nEntry {entry:.2f} -> {price:.2f}\n+{price-entry:.2f}")
                        active_trade = None
                    elif price <= active_trade["sl"]:
                        send_tg(f"❌ <b>SL HIT BUY</b>\nEntry {entry:.2f} -> {price:.2f}\n{price-entry:.2f}")
                        active_trade = None
                else:
                    if price <= active_trade["tp"]:
                        send_tg(f"✅ <b>TP HIT SELL</b>\nEntry {entry:.2f} -> {price:.2f}\n+{entry-price:.2f}")
                        active_trade = None
                    elif price >= active_trade["sl"]:
                        send_tg(f"❌ <b>SL HIT SELL</b>\nEntry {entry:.2f} -> {price:.2f}\n{entry-price:.2f}")
                        active_trade = None
                if active_trade:
                    time.sleep(60); continue

            # MANDATORY 1: Volume surge + increasing
            vol_surge = c0["v"] > c0["vol_ma20"]
            vol_inc = c0["v"] > c1["v"]
            if not (vol_surge and vol_inc):
                time.sleep(60); continue

            # MANDATORY 2: Momentum
            buy_mom = (c0["ema9"] > c1["ema9"]) and (c0["rsi"] > c1["rsi"]) and (c0["roc"] > 0)
            sell_mom = (c0["ema9"] < c1["ema9"]) and (c0["rsi"] < c1["rsi"]) and (c0["roc"] < 0)

            buy_score = 0
            sell_score = 0
            if price > c0["ema20"]: buy_score+=1
            if price < c0["ema20"]: sell_score+=1
            if c0["ema9"] > c0["ema21"]: buy_score+=1
            if c0["ema9"] < c0["ema21"]: sell_score+=1
            if rsi < 65: buy_score+=1
            if rsi > 35: sell_score+=1
            if c0["roc"] > 0.05: buy_score+=1
            if c0["roc"] < -0.05: sell_score+=1

            if buy_mom and buy_score >=3:
                tp = price * 1.006
                sl = price * 0.996
                active_trade = {"dir":"BUY","entry":price,"tp":tp,"sl":sl}
                send_tg(f"🟢 <b>BUY V8.2 POWER</b>\nPrice {price:.2f}\nRSI {rsi:.1f}↑\nVol {c0['v']:.2f} > MA20 {c0['vol_ma20']:.2f} + INC\nROC {c0['roc']:.2f}%\nScore {buy_score}/4\nTP {tp:.2f} SL {sl:.2f}")
            elif sell_mom and sell_score >=3:
                tp = price * 0.994
                sl = price * 1.004
                active_trade = {"dir":"SELL","entry":price,"tp":tp,"sl":sl}
                send_tg(f"🔴 <b>SELL V8.2 POWER</b>\nPrice {price:.2f}\nRSI {rsi:.1f}↓\nVol {c0['v']:.2f} > MA20 {c0['vol_ma20']:.2f} + INC\nROC {c0['roc']:.2f}%\nScore {sell_score}/4\nTP {tp:.2f} SL {sl:.2f}")

            time.sleep(60)
        except Exception as e:
            print(f"CHECK ERR {e}")
            time.sleep(10)

def telegram_loop():
    print("=== BOT POLLING STARTED ===")
    offset = 0
    while True:
        try:
            r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                             params={"offset": offset, "timeout": 25}, timeout=30).json()
            for upd in r.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message", {})
                text = msg.get("text","")
                chat = str(msg.get("chat",{}).get("id",""))
                if chat!= CHAT_ID: continue
                if "/status" in text or "/start" in text:
                    tr = "No active trade"
                    if active_trade:
                        tr = f"{active_trade['dir']} {active_trade['entry']:.2f} TP {active_trade['tp']:.2f} SL {active_trade['sl']:.2f}"
                    send_tg(f"✅ <b>XAU V8.2 POWER LIVE</b>\nPrice: {last_price:.2f}\nRSI: {last_rsi:.2f}\nLast: {last_check}\nTrade: {tr}")
        except Exception as e:
            print(f"POLL ERR {e}")
            time.sleep(3)

@app.route("/")
def home():
    return f"XAU V8.2 POWER {last_price} {last_check}"

threading.Thread(target=telegram_loop, daemon=True).start()
threading.Thread(target=check_market, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
