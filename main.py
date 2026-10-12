import os, time, threading, requests
from flask import Flask
import yfinance as yf
import pandas as pd
import ta

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

app = Flask(__name__)
last_price = 0
last_spot = 0
last_rsi = 0
last_check = "Never"
active_trade = None

def send_tg(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"SEND FAIL {e}")

def get_spot_price():
    urls = [
        "https://api.gold-api.com/price/XAU",
        "https://api.metals.live/v1/spot",
    ]
    for url in urls:
        try:
            r = requests.get(url, timeout=8).json()
            if "price" in r:
                p = float(r["price"])
                print(f"SPOT API {url} OK {p}", flush=True)
                return p
            if isinstance(r, list) and len(r)>0 and "gold" in r[0]:
                p = float(r[0]["gold"])
                print(f"SPOT API metals.live OK {p}", flush=True)
                return p
        except Exception as e:
            print(f"SPOT API {url} FAIL {e}", flush=True)
            continue
    return None

def get_history():
    try:
        df = yf.download("GC=F", period="7d", interval="5m", progress=False, auto_adjust=True, prepost=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        close = df['Close']
        if len(close) < 50:
            return None

        ema9 = float(ta.trend.ema_indicator(close, window=9).iloc[-1])
        ema20 = float(ta.trend.ema_indicator(close, window=20).iloc[-1])
        ema21 = float(ta.trend.ema_indicator(close, window=21).iloc[-1])
        ema_len = 200 if len(close) >= 200 else 100
        ema200 = float(ta.trend.ema_indicator(close, window=ema_len).iloc[-1])
        rsi = float(ta.momentum.rsi(close, window=14).iloc[-1])
        roc = float(ta.momentum.roc(close, window=9).iloc[-1])
        fut_price = float(close.iloc[-1])
        return {"ema9": ema9, "ema20": ema20, "ema21": ema21, "ema200": ema200, "rsi": rsi, "roc": roc, "fut_price": fut_price, "ema_len": ema_len}
    except Exception as e:
        print(f"HISTORY FAIL {e}", flush=True)
        return None

def get_data():
    spot = get_spot_price()
    hist = get_history()
    if hist is None:
        return None
    if spot is None:
        spot = hist["fut_price"] - 18.0
        print(f"USING FALLBACK SPOT {spot} from FUT {hist['fut_price']}", flush=True)

    premium = hist["fut_price"] - spot
    adj_ema9 = hist["ema9"] - premium
    adj_ema20 = hist["ema20"] - premium
    adj_ema21 = hist["ema21"] - premium
    adj_ema200 = hist["ema200"] - premium

    return {
        "price": spot,
        "fut_price": hist["fut_price"],
        "ema9": adj_ema9,
        "ema20": adj_ema20,
        "ema21": adj_ema21,
        "ema200": adj_ema200,
        "rsi": hist["rsi"],
        "roc": hist["roc"],
        "ema_len": hist["ema_len"],
        "premium": premium
    }

def check_market():
    global last_price, last_spot, last_rsi, last_check, active_trade
    print("MARKET V10.4 SPOT+TP/SL STARTED", flush=True)

    while True:
        try:
            d = get_data()
            if d is None:
                time.sleep(60)
                continue

            price = d["price"]; ema9 = d["ema9"]; ema20 = d["ema20"]; ema21 = d["ema21"]; ema200 = d["ema200"]
            rsi = d["rsi"]; roc = d["roc"]

            last_price = price; last_spot = price; last_rsi = rsi; last_check = time.strftime("%H:%M:%S")
            print(f"CHECK SPOT {price:.2f} FUT {d['fut_price']:.2f} PREM {d['premium']:.2f} RSI {rsi:.1f}", flush=True)

            if active_trade:
                entry = active_trade["entry"]
                if active_trade["dir"] == "BUY":
                    if price >= active_trade["tp"]:
                        send_tg(f"✅ <b>TP HIT BUY</b>\nEntry {entry:.2f} -> {price:.2f}\nProfit +0.6%"); active_trade=None
                    elif price <= active_trade["sl"]:
                        send_tg(f"❌ <b>SL HIT BUY</b>\nEntry {entry:.2f} -> {price:.2f}\nLoss -0.3%"); active_trade=None
                else:
                    if price <= active_trade["tp"]:
                        send_tg(f"✅ <b>TP HIT SELL</b>\nEntry {entry:.2f} -> {price:.2f}\nProfit +0.6%"); active_trade=None
                    elif price >= active_trade["sl"]:
                        send_tg(f"❌ <b>SL HIT SELL</b>\nEntry {entry:.2f} -> {price:.2f}\nLoss -0.3%"); active_trade=None
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
                tp = price*1.006
                sl = price*0.997
                active_trade={"dir":"BUY","entry":price,"tp":tp,"sl":sl}
                send_tg(f"🟢 <b>BUY 1:2 RR</b>\nSPOT {price:.2f} (FUT {d['fut_price']:.2f})\nEntry {price:.2f}\nTP {tp:.2f} (+0.6%)\nSL {sl:.2f} (-0.3%)\nEMA{d['ema_len']} {ema200:.2f}\nRSI {rsi:.1f} ROC {roc:.2f}%\nScore {buy_score}/5")
            elif sell_mom and sell_score >= 4:
                tp = price*0.994
                sl = price*1.003
                active_trade={"dir":"SELL","entry":price,"tp":tp,"sl":sl}
                send_tg(f"🔴 <b>SELL 1:2 RR</b>\nSPOT {price:.2f} (FUT {d['fut_price']:.2f})\nEntry {price:.2f}\nTP {tp:.2f} (-0.6%)\nSL {sl:.2f} (+0.3%)\nEMA{d['ema_len']} {ema200:.2f}\nRSI {rsi:.1f} ROC {roc:.2f}%\nScore {sell_score}/5")

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
                    if active_trade: tr=f"{active_trade['dir']} E:{active_trade['entry']:.2f} TP:{active_trade['tp']:.2f} SL:{active_trade['sl']:.2f}"
                    send_tg(f"✅ <b>V10.4 SPOT LIVE</b>\nSPOT Price: {last_price:.2f}\nFUT Price: {d['fut_price']:.2f}\nRSI: {last_rsi:.2f}\nLast: {last_check}\n{tr}")
        except: time.sleep(3)

@app.route("/")
def home(): return f"V10.4 SPOT {last_price} {last_check}"

threading.Thread(target=telegram_loop, daemon=True).start()
threading.Thread(target=check_market, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
