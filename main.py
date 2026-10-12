import os, time, threading, requests
from flask import Flask
import yfinance as yf
import pandas as pd
import ta

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

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

def get_data():
    try:
        # Gold Futures = same as XAUUSD
        df = yf.download("GC=F", period="2d", interval="5m", progress=False)
        if df.empty:
            print("YF EMPTY", flush=True)
            return None
        # flatten if multi-index
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        close = df['Close']
        price = float(close.iloc[-1])

        ema9 = float(ta.trend.ema_indicator(close, window=9).iloc[-1])
        ema20 = float(ta.trend.ema_indicator(close, window=20).iloc[-1])
        ema21 = float(ta.trend.ema_indicator(close, window=21).iloc[-1])
        ema200 = float(ta.trend.ema_indicator(close, window=200).iloc[-1])
        rsi = float(ta.momentum.rsi(close, window=14).iloc[-1])
        roc = float(ta.momentum.roc(close, window=9).iloc[-1])

        print(f"YF OK Price {price:.2f} RSI {rsi:.1f}", flush=True)
        return {"price": price, "ema9": ema9, "ema20": ema20, "ema21": ema21, "ema200": ema200, "rsi": rsi, "roc": roc}
    except Exception as e:
        print(f"YF FAIL {e}", flush=True)
        return None

def check_market():
    global last_price, last_rsi, last_check, active_trade
    print("MARKET V10 YFINANCE STARTED", flush=True)
    
    while True:
        try:
            d = get_data()
            if d is None:
                time.sleep(60)
                continue

            price = d["price"]
            ema9 = d["ema9"]; ema20 = d["ema20"]; ema21 = d["ema21"]; ema200 = d["ema200"]
            rsi = d["rsi"]; roc = d["roc"]

            last_price = price; last_rsi = rsi; last_check = time.strftime("%H:%M:%S")

            if active_trade:
                entry = active_trade["entry"]
                if active_trade["dir"] == "BUY":
                    if price >= active_trade["tp"]:
                        send_tg(f"✅ <b>TP HIT BUY</b>\n{entry:.2f} -> {price:.2f}"); active_trade=None
                    elif price <= active_trade["sl"]:
                        send_tg(f"❌ <b>SL HIT BUY</b>\n{entry:.2f} -> {price:.2f}"); active_trade=None
                else:
                    if price <= active_trade["tp"]:
                        send_tg(f"✅ <b>TP HIT SELL</b>\n{entry:.2f} -> {price:.2f}"); active_trade=None
                    elif price >= active_trade["sl"]:
                        send_tg(f"❌ <b>SL HIT SELL</b>\n{entry:.2f} -> {price:.2f}"); active_trade=None
                if active_trade:
                    time.sleep(90); continue

            if rsi < 30 or rsi > 80:
                time.sleep(90); continue
            if abs(price - ema200)/price*100 < 0.08:
                time.sleep(90); continue

            above_200 = price > ema200
            below_200 = price < ema200
            buy_rsi_ok = 45 < rsi < 68
            sell_rsi_ok = 33 < rsi < 55

            buy_mom = (price > ema9) and buy_rsi_ok and (roc > 0.02) and above_200
            sell_mom = (price < ema9) and sell_rsi_ok and (roc < -0.02) and below_200

            buy_score = (1 if price > ema20 else 0) + (1 if ema9 > ema21 else 0) + (1 if buy_rsi_ok else 0) + (1 if roc > 0.05 else 0) + (1 if above_200 else 0)
            sell_score = (1 if price < ema20 else 0) + (1 if ema9 < ema21 else 0) + (1 if sell_rsi_ok else 0) + (1 if roc < -0.05 else 0) + (1 if below_200 else 0)

            if buy_mom and buy_score >= 4:
                active_trade={"dir":"BUY","entry":price,"tp":price*1.006,"sl":price*0.997}
                send_tg(f"🟢 <b>BUY 1:2 RR</b>\nPrice {price:.2f}\nEMA200 {ema200:.2f}\nRSI {rsi:.1f} ROC {roc:.2f}%\nScore {buy_score}/5")
            elif sell_mom and sell_score >= 4:
                active_trade={"dir":"SELL","entry":price,"tp":price*0.994,"sl":price*1.003}
                send_tg(f"🔴 <b>SELL 1:2 RR</b>\nPrice {price:.2f}\nEMA200 {ema200:.2f}\nRSI {rsi:.1f} ROC {roc:.2f}%\nScore {sell_score}/5")

            time.sleep(90)
        except Exception as e:
            print(f"ERR {e}", flush=True); time.sleep(30)

def telegram_loop():
    global last_price, last_rsi, last_check
    offset=0
    while True:
        try:
            r=requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", params={"offset":offset,"timeout":25}, timeout=30).json()
            for upd in r.get("result", []):
                offset=upd["update_id"]+1
                msg=upd.get("message",{}); text=msg.get("text",""); chat=str(msg.get("chat",{}).get("id",""))
                if chat!=CHAT_ID: continue
                if "/status" in text or "/start" in text:
                    d = get_data()
                    if d:
                        last_price = d["price"]; last_rsi = d["rsi"]; last_check = time.strftime("%H:%M:%S")
                    tr="No trade"
                    if active_trade: tr=f"{active_trade['dir']} E:{active_trade['entry']:.2f}"
                    send_tg(f"✅ <b>V10 YFINANCE LIVE</b>\nPrice: {last_price:.2f}\nRSI: {last_rsi:.2f}\nLast: {last_check}\n{tr}")
        except: time.sleep(3)

@app.route("/")
def home(): return f"V10 {last_price} {last_check}"

threading.Thread(target=telegram_loop, daemon=True).start()
threading.Thread(target=check_market, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
