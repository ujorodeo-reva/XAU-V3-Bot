import os, time, threading, requests
import pandas as pd
import numpy as np
from flask import Flask

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYMBOL = "PAXGUSDT"
BINANCE_URL = f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval=5m&limit=100"

app = Flask(__name__)

last_price = 0
last_rsi = 0
last_check = "Never"
active_trade = None # {"dir": "BUY", "entry": 4187.5, "tp":..., "sl":...}

def send_tg(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"SEND FAIL {e}")

def get_klines():
    try:
        r = requests.get(BINANCE_URL, timeout=10).json()
        df = pd.DataFrame(r, columns=["t","o","h","l","c","v","ct","q","n","tb","tq","ig"])
        for col in ["o","h","l","c","v"]:
            df[col] = df[col].astype(float)
        return df
    except Exception as e:
        print(f"BINANCE FAIL {e}")
        return None

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def check_market():
    global last_price, last_rsi, last_check, active_trade
    while True:
        try:
            df = get_klines()
            if df is None or len(df) < 30:
                time.sleep(30); continue

            # Indicators
            df["ema9"] = df["c"].ewm(span=9).mean()
            df["ema21"] = df["c"].ewm(span=21).mean()
            df["ema20"] = df["c"].ewm(span=20).mean()
            df["rsi"] = calc_rsi(df["c"], 14)
            df["vol_ma20"] = df["v"].rolling(20).mean()
            df["roc"] = df["c"].pct_change(3) * 100 # 3 candle momentum

            # Last 2 candles
            c0 = df.iloc[-1]
            c1 = df.iloc[-2]

            price = c0["c"]
            rsi = c0["rsi"]
            last_price = price
            last_rsi = rsi
            last_check = time.strftime("%H:%M:%S")
            print(f"CHECK {price:.2f} RSI {rsi:.1f} Vol {c0['v']:.1f} vs MA {c0['vol_ma20']:.1f}")

            # --- TRACK ACTIVE TRADE TP/SL ---
            if active_trade:
                entry = active_trade["entry"]
                if active_trade["dir"] == "BUY":
                    if price >= active_trade["tp"]:
                        send_tg(f"✅ <b>TP HIT - BUY WIN</b>\nEntry: {entry:.2f}\nExit: {price:.2f}\nProfit: +{price-entry:.2f}")
                        active_trade = None
                    elif price <= active_trade["sl"]:
                        send_tg(f"❌ <b>SL HIT - BUY LOSS</b>\nEntry: {entry:.2f}\nExit: {price:.2f}\nLoss: {price-entry:.2f}")
                        active_trade = None
                else: # SELL
                    if price <= active_trade["tp"]:
                        send_tg(f"✅ <b>TP HIT - SELL WIN</b>\nEntry: {entry:.2f}\nExit: {price:.2f}\nProfit: +{entry-price:.2f}")
                        active_trade = None
                    elif price >= active_trade["sl"]:
                        send_tg(f"❌ <b>SL HIT - SELL LOSS</b>\nEntry: {entry:.2f}\nExit: {price:.2f}\nLoss: {entry-price:.2f}")
                        active_trade = None
                # don't open new trade while one active
                if active_trade:
                    time.sleep(60); continue

            # --- MANDATORY FILTER 1: VOLUME SURGE + INCREASING ---
            vol_surge = c0["v"] > c0["vol_ma20"]
            vol_increasing = c0["v"] > c1["v"]
            if not (vol_surge and vol_increasing):
                time.sleep(60); continue

            # --- MANDATORY FILTER 2: MOMENTUM DIRECTION ---
            ma9_slope_up = c0["ema9"] > c1["ema9"]
            rsi_slope_up = c0["rsi"] > c1["rsi"]
            roc_up = c0["roc"] > 0

            ma9_slope_down = c0["ema9"] < c1["ema9"]
            rsi_slope_down = c0["rsi"] < c1["rsi"]
            roc_down = c0["roc"] < 0

            buy_momentum = ma9_slope_up and rsi_slope_up and roc_up
            sell_momentum = ma9_slope_down and rsi_slope_down and roc_down

            # --- 3/4 CONFIRMATIONS ---
            confirmations_buy = 0
            confirmations_sell = 0

            # 1. Trend: price vs EMA20
            if price > c0["ema20"]: confirmations_buy += 1
            if price < c0["ema20"]: confirmations_sell += 1
            # 2. EMA cross
            if c0["ema9"] > c0["ema21"]: confirmations_buy += 1
            if c0["ema9"] < c0["ema21"]: confirmations_sell += 1
            # 3. RSI level not extreme opposite
            if rsi < 65: confirmations_buy += 1
            if rsi > 35: confirmations_sell += 1
            # 4. ROC strength >0.05%
            if c0["roc"] > 0.05: confirmations_buy += 1
            if c0["roc"] < -0.05: confirmations_sell += 1

            signal = None
            if buy_momentum and confirmations_buy >= 3:
                tp = price * 1.006 # +0.6%
                sl = price * 0.996 # -0.4%
                active_trade = {"dir": "BUY", "entry": price, "tp": tp, "sl": sl}
                signal = (f"🟢 <b>BUY SIGNAL V8.2 POWER</b>\n"
                          f"Price: {price:.2f}\nRSI: {rsi:.2f} ↗\n"
                          f"Vol: {c0['v']:.2f} > MA20 {c0['vol_ma20']:.2f} + INC\n"
                          f"Momentum: MA9↑ RSI↑ ROC {c0['roc']:.2f}%↑\n"
                          f"Score: {confirmations_buy}/4\n"
                          f"TP: {tp:.2f} | SL: {sl:.2f}\nTracking...")

            elif sell_momentum and confirmations_sell >= 3:
                tp = price * 0.994
                sl = price * 1.004
                active_trade = {"dir": "SELL", "entry": price, "tp": tp, "sl": sl}
                signal = (f"🔴 <b>SELL SIGNAL V8.2 POWER</b>\n"
                          f"Price: {price:.2f}\nRSI: {rsi:.2f} ↘\n"
                          f"Vol: {c0['v']:.2f} > MA20 {c0['vol_ma20']:.2f} + INC\n"
                          f"Momentum: MA9↓ RSI↓ ROC {c0['roc']:.2f}%↓\n"
                          f"Score: {confirmations_sell}/4\n"
                          f"TP: {tp:.2f} | SL: {sl:.2f}\nTracking...")

            if signal:
                print(signal)
                send_tg(signal)

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
                    trade_txt = "No active trade"
                    if active_trade:
                        trade_txt = f"{active_trade['dir']} Entry {active_trade['entry']:.2f} TP {active_trade['tp']:.2f} SL {active_trade['sl']:.2f}"
                    send_tg(f"✅ <b>XAU V8.2 POWER LIVE</b>\n"
                            f"Price: {last_price:.2f}\nRSI: {last_rsi:.2f}\n"
                            f"Last: {last_check}\nTrade: {trade_txt}\nSymbol: {SYMBOL}")
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
