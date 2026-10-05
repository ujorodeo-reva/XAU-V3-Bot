import os, time, threading, requests
import pandas as pd
from flask import Flask

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYMBOL = "PAXGUSDT"

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
    # 1. Try Binance
    urls = [
        f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval=5m&limit=100",
        f"https://data-api.binance.vision/api/v3/klines?symbol={SYMBOL}&interval=5m&limit=100",
    ]
    for url in urls:
        try:
            r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10).json()
            if isinstance(r, list) and len(r)>5:
                df = pd.DataFrame(r, columns=["t","o","h","l","c","v","ct","q","n","tb","tq","ig"])
                for col in ["o","h","l","c","v"]: df[col]=df[col].astype(float)
                print(f"OK BINANCE {url[:30]}")
                return df
        except Exception as e:
            print(f"FAIL BINANCE {e}")

    # 2. Try OKX - this works on Render
    try:
        url = "https://www.okx.com/api/v5/market/candles?instId=PAXG-USDT&bar=5m&limit=100"
        r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10).json()
        data = r.get("data", [])
        if data and len(data)>5:
            data = list(reversed(data)) # OKX returns newest first
            df = pd.DataFrame(data, columns=["t","o","h","l","c","v","volCcy","volCcyQ","c2"])
            for col in ["o","h","l","c","v"]: df[col]=df[col].astype(float)
            print(f"OK OKX candles {len(df)}")
            return df
    except Exception as e:
        print(f"FAIL OKX {e}")

    # 3. Last resort - get price only from CoinGecko for /status
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=pax-gold&vs_currencies=usd", timeout=10).json()
        price = float(r["pax-gold"]["usd"])
        print(f"OK COINGECKO price {price}")
        # create fake df with that price
        df = pd.DataFrame({"c":[price]*30, "v":[1]*30, "o":[price]*30, "h":[price]*30, "l":[price]*30})
        return df
    except Exception as e:
        print(f"FAIL COINGECKO {e}")

    return None

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def check_market():
    global last_price, last_rsi, last_check, active_trade
    print("MARKET CHECK THREAD STARTED", flush=True)
    time.sleep(3)
    while True:
        try:
            df = get_klines()
            if df is None or len(df) < 20:
                print("No data, retry 30s", flush=True)
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
            rsi = float(c0["rsi"]) if not pd.isna(c0["rsi"]) else 50

            last_price = price
            last_rsi = rsi
            last_check = time.strftime("%H:%M:%S")
            print(f"CHECK {price:.2f} RSI {rsi:.1f}", flush=True)

            if active_trade:
                entry = active_trade["entry"]
                if active_trade["dir"] == "BUY":
                    if price >= active_trade["tp"]:
                        send_tg(f"✅ <b>TP HIT BUY</b>\nEntry {entry:.2f} -> {price:.2f}\n+{price-entry:.2f}")
                        active_trade=None
                    elif price <= active_trade["sl"]:
                        send_tg(f"❌ <b>SL HIT BUY</b>\nEntry {entry:.2f} -> {price:.2f}")
                        active_trade=None
                else:
                    if price <= active_trade["tp"]:
                        send_tg(f"✅ <b>TP HIT SELL</b>\nEntry {entry:.2f} -> {price:.2f}")
                        active_trade=None
                    elif price >= active_trade["sl"]:
                        send_tg(f"❌ <b>SL HIT SELL</b>\nEntry {entry:.2f} -> {price:.2f}")
                        active_trade=None
                if active_trade:
                    time.sleep(60); continue

            vol_surge = c0["v"] > c0["vol_ma20"] if not pd.isna(c0["vol_ma20"]) else True
            vol_inc = c0["v"] >= c1["v"]
            if not (vol_surge and vol_inc):
                time.sleep(60); continue

            buy_mom = (c0["ema9"] > c1["ema9"]) and (c0["rsi"] > c1["rsi"]) and (c0["roc"] > 0)
            sell_mom = (c0["ema9"] < c1["ema9"]) and (c0["rsi"] < c1["rsi"]) and (c0["roc"] < 0)

            buy_score = (1 if price > c0["ema20"] else 0) + (1 if c0["ema9"] > c0["ema21"] else 0) + (1 if rsi < 65 else 0) + (1 if c0["roc"] > 0.05 else 0)
            sell_score = (1 if price < c0["ema20"] else 0) + (1 if c0["ema9"] < c0["ema21"] else 0) + (1 if rsi > 35 else 0) + (1 if c0["roc"] < -0.05 else 0)

            if buy_mom and buy_score>=3:
                tp = price*1.006; sl=price*0.996
                active_trade={"dir":"BUY","entry":price,"tp":tp,"sl":sl}
                send_tg(f"🟢 <b>BUY V8.2 POWER</b>\nPrice {price:.2f}\nRSI {rsi:.1f}↑ Vol INC\nROC {c0['roc']:.2f}%\nScore {buy_score}/4\nTP {tp:.2f} SL {sl:.2f}")
            elif sell_mom and sell_score>=3:
                tp=price*0.994; sl=price*1.004
                active_trade={"dir":"SELL","entry":price,"tp":tp,"sl":sl}
                send_tg(f"🔴 <b>SELL V8.2 POWER</b>\nPrice {price:.2f}\nRSI {rsi:.1f}↓ Vol INC\nROC {c0['roc']:.2f}%\nScore {sell_score}/4\nTP {tp:.2f} SL {sl:.2f}")

            time.sleep(60)
        except Exception as e:
            print(f"CHECK ERR {e}", flush=True)
            time.sleep(10)

def telegram_loop():
    print("BOT POLLING STARTED", flush=True)
    offset=0
    while True:
        try:
            r=requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", params={"offset":offset,"timeout":25}, timeout=30).json()
            for upd in r.get("result", []):
                offset=upd["update_id"]+1
                msg=upd.get("message",{}); text=msg.get("text",""); chat=str(msg.get("chat",{}).get("id",""))
                if chat!=CHAT_ID: continue
                if "/status" in text or "/start" in text:
                    tr="No active trade"
                    if active_trade: tr=f"{active_trade['dir']} {active_trade['entry']:.2f} TP {active_trade['tp']:.2f} SL {active_trade['sl']:.2f}"
                    send_tg(f"✅ <b>XAU V8.2 POWER LIVE</b>\nPrice: {last_price:.2f}\nRSI: {last_rsi:.2f}\nLast: {last_check}\nTrade: {tr}")
        except Exception as e:
            print(f"POLL ERR {e}", flush=True)
            time.sleep(3)

@app.route("/")
def home(): return f"XAU V8.2 {last_price} {last_check}"

threading.Thread(target=telegram_loop, daemon=True).start()
threading.Thread(target=check_market, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
