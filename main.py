import os, time, threading, requests
from flask import Flask
from tradingview_ta import TA_Handler, Interval

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

def get_tv_data():
    try:
        handler = TA_Handler(
            symbol="XAUUSD",
            screener="forex",
            exchange="OANDA",
            interval=Interval.INTERVAL_5_MINUTES
        )
        a = handler.get_analysis()
        print(f"TV RAW: {a.indicators}", flush=True)
        return a.indicators
    except Exception as e:
        print(f"TV FAIL {e}", flush=True)
        return None

def check_market():
    global last_price, last_rsi, last_check, active_trade
    print("MARKET CHECK THREAD STARTED V9.2", flush=True)
    # instant try
    ind = get_tv_data()
    if ind:
        last_price = float(ind["close"])
        last_rsi = float(ind.get("RSI", 0))
        last_check = time.strftime("%H:%M:%S")
    
    while True:
        try:
            ind = get_tv_data()
            if ind is None:
                time.sleep(30); continue

            price = float(ind["close"])
            ema9 = float(ind.get("EMA9", ind.get("EMA10", price)))
            ema21 = float(ind.get("EMA20", ind.get("EMA21", price)))
            ema20 = float(ind.get("EMA20", price))
            ema200 = float(ind.get("EMA200", price))
            rsi = float(ind.get("RSI", 50))
            roc = float(ind.get("ROC", 0))

            last_price = price; last_rsi = rsi; last_check = time.strftime("%H:%M:%S")
            print(f"CHECK {price:.2f} RSI {rsi:.1f}", flush=True)

            if active_trade:
                entry = active_trade["entry"]
                if active_trade["dir"] == "BUY":
                    if price >= active_trade["tp"]:
                        send_tg(f"✅ <b>TP HIT BUY</b>\n{entry:.2f} -> {price:.2f}")
                        active_trade=None
                    elif price <= active_trade["sl"]:
                        send_tg(f"❌ <b>SL HIT BUY</b>"); active_trade=None
                else:
                    if price <= active_trade["tp"]:
                        send_tg(f"✅ <b>TP HIT SELL</b>\n{entry:.2f} -> {price:.2f}")
                        active_trade=None
                    elif price >= active_trade["sl"]:
                        send_tg(f"❌ <b>SL HIT SELL</b>"); active_trade=None
                if active_trade: time.sleep(60); continue

            if rsi < 30 or rsi > 80: time.sleep(60); continue
            if abs(price - ema200)/price*100 < 0.08: time.sleep(60); continue

            above_200 = price > ema200; below_200 = price < ema200
            buy_rsi_ok = 45 < rsi < 68
            sell_rsi_ok = 33 < rsi < 55

            buy_mom = (price > ema9) and buy_rsi_ok and (roc > 0.02) and above_200
            sell_mom = (price < ema9) and sell_rsi_ok and (roc < -0.02) and below_200

            buy_score = (1 if price > ema20 else 0) + (1 if ema9 > ema21 else 0) + (1 if buy_rsi_ok else 0) + (1 if roc > 0.05 else 0) + (1 if above_200 else 0)
            sell_score = (1 if price < ema20 else 0) + (1 if ema9 < ema21 else 0) + (1 if sell_rsi_ok else 0) + (1 if roc < -0.05 else 0) + (1 if below_200 else 0)

            if buy_mom and buy_score>=4:
                active_trade={"dir":"BUY","entry":price,"tp":price*1.006,"sl":price*0.997}
                send_tg(f"🟢 <b>BUY</b>\n{price:.2f} RSI {rsi:.1f} Score {buy_score}/5")
            elif sell_mom and sell_score>=4:
                active_trade={"dir":"SELL","entry":price,"tp":price*0.994,"sl":price*1.003}
                send_tg(f"🔴 <b>SELL</b>\n{price:.2f} RSI {rsi:.1f} Score {sell_score}/5")

            time.sleep(60)
        except Exception as e:
            print(f"ERR {e}", flush=True); time.sleep(10)

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
                    # FORCE FETCH ON COMMAND
                    ind = get_tv_data()
                    if ind:
                        last_price = float(ind["close"])
                        last_rsi = float(ind.get("RSI", 0))
                        last_check = time.strftime("%H:%M:%S")
                    tr="No trade"
                    if active_trade: tr=f"{active_trade['dir']} E:{active_trade['entry']:.2f}"
                    send_tg(f"✅ <b>V9.2 TV OANDA LIVE</b>\nPrice: {last_price:.2f}\nRSI: {last_rsi:.2f}\nLast: {last_check}\n{tr}")
        except: time.sleep(3)

@app.route("/")
def home(): return f"V9.2 {last_price} {last_check}"

threading.Thread(target=telegram_loop, daemon=True).start()
threading.Thread(target=check_market, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
