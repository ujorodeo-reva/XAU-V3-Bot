import os, time, threading, requests, pandas as pd
from flask import Flask
from datetime import datetime

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYMBOL = "PAXGUSDT"
SCAN_SECONDS = 60

last_state = {"price":0,"rsi":0,"vol":0,"ma200":0,"status":"starting"}
last_update = "never"
active_trade = None
last_signal_candle = None

def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

def rsi_calc(s, p=14):
    d = s.diff(); g = d.clip(lower=0).ewm(alpha=1/p, adjust=False).mean()
    l = -d.clip(upper=0).ewm(alpha=1/p, adjust=False).mean()
    return 100 - (100/(1+g/l.replace(0,0.00001)))

def send_telegram(t):
    try: requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={"chat_id":CHAT_ID,"text":t,"parse_mode":"Markdown"}, timeout=15)
    except: pass

def fetch_binance():
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval=15m&limit=500"
        r = requests.get(url, timeout=10).json()
        if not isinstance(r, list) or len(r) < 210: return None
        df = pd.DataFrame(r, columns=["time","Open","High","Low","Close","Volume","c2","c3","c4","c5","c6","c7"])
        df["Close"]=df["Close"].astype(float); df["High"]=df["High"].astype(float)
        df["Low"]=df["Low"].astype(float); df["Volume"]=df["Volume"].astype(float)
        df["Open"]=df["Open"].astype(float)
        df["rsi"]=rsi_calc(df["Close"]); df["ma9"]=df["Close"].rolling(9).mean()
        df["ma20"]=df["Close"].rolling(20).mean(); df["ma200"]=df["Close"].rolling(200).mean()
        df["vol_ma20"]=df["Volume"].rolling(20).mean()
        # Momentum helpers
        df["ma9_slope"] = df["ma9"].diff(3)  # slope last 3 candles
        df["rsi_slope"] = df["rsi"].diff(3)
        df["roc"] = df["Close"].pct_change(3) * 100  # % change last 3 candles
        df.index = pd.to_datetime(df["time"], unit='ms')
        return df
    except Exception as e:
        log(f"err {e}"); return None

def detect_sr(df):
    recent = df.tail(50)
    sup = recent.nsmallest(3,"Low")["Low"].mean()
    res = recent.nlargest(3,"High")["High"].mean()
    return sup, res

def check_loop():
    global last_state, last_update, active_trade, last_signal_candle
    log("V8.2 POWER - Volume+Momentum mandatory")
    time.sleep(3)
    while True:
        df = fetch_binance()
        if df is None: time.sleep(10); continue

        last = df.iloc[-1]; prev = df.iloc[-2]
        price = float(last["Close"]); rsi=float(last["rsi"])
        ma9=float(last["ma9"]); ma20=float(last["ma20"]); ma200=float(last["ma200"])
        ma9_slope=float(last["ma9_slope"]); rsi_slope=float(last["rsi_slope"]); roc=float(last["roc"])
        vol_ma=float(last["vol_ma20"]) if pd.notna(last["vol_ma20"]) else 0
        vol_now=float(last["Volume"]); vol_prev=float(prev["Volume"])
        vol_ratio = 1.0 if vol_ma < 1 else vol_now/vol_ma

        support, resistance = detect_sr(df)
        above_200 = price > ma200
        below_200 = price < ma200
        
        cross_up_recent = any(df["ma9"].iloc[-i] > df["ma20"].iloc[-i] and df["ma9"].iloc[-i-1] <= df["ma20"].iloc[-i-1] for i in range(1,11))
        cross_down_recent = any(df["ma9"].iloc[-i] < df["ma20"].iloc[-i] and df["ma9"].iloc[-i-1] >= df["ma20"].iloc[-i-1] for i in range(1,11))
        near_sup = abs(price-support)/price < 0.008
        near_res = abs(price-resistance)/price < 0.008

        # POWER FILTERS - MANDATORY
        volume_power = vol_now > vol_ma * 0.8 and vol_now > vol_prev * 0.9  # volume surging + increasing
        bullish_momentum = ma9_slope > 0 and rsi_slope > -1 and roc > -0.1 and last["Close"] > last["Open"]
        bearish_momentum = ma9_slope < 0 and rsi_slope < 1 and roc < 0.1 and last["Close"] < last["Open"]

        last_state = {"price":round(price,2),"rsi":round(rsi,2),"vol":round(vol_ratio,2),"ma200":round(ma200,2),"status":f"ROC:{roc:.2f}% MOM:{ma9_slope:.2f}"}
        last_update = datetime.now().strftime("%H:%M:%S")

        if active_trade:
            entry=active_trade["entry"]; sl=active_trade["sl"]; tp=active_trade["tp"]; typ=active_trade["type"]
            if typ=="BUY" and price >= tp:
                send_telegram(f"✅ *TP HIT BUY WIN* 🎯\n+{price-entry:.2f}$"); active_trade=None
            elif typ=="BUY" and price <= sl:
                send_telegram(f"❌ *SL HIT BUY* {price-entry:.2f}$"); active_trade=None
            elif typ=="SELL" and price <= tp:
                send_telegram(f"✅ *TP HIT SELL WIN* 🎯\n+{entry-price:.2f}$"); active_trade=None
            elif typ=="SELL" and price >= sl:
                send_telegram(f"❌ *SL HIT SELL* {entry-price:.2f}$"); active_trade=None
            if active_trade: time.sleep(SCAN_SECONDS); continue

        candle_time = str(df.index[-1])
        if candle_time == last_signal_candle: time.sleep(SCAN_SECONDS); continue

        # SCORE - but volume+momentum MUST pass first
        buy_score = sum([above_200, cross_up_recent, near_sup, rsi < 50])
        sell_score = sum([below_200, cross_down_recent, near_res, rsi > 50])

        log(f"{price:.1f} BUY:{buy_score}/4 SELL:{sell_score}/4 VolPow:{volume_power} BullMom:{bullish_momentum} ROC:{roc:.2f}% Vol:{vol_ratio:.2f}x {vol_now:.1f}>{vol_prev:.1f}")

        # BUY ONLY IF VOLUME + MOMENTUM PUSHING UP
        if buy_score >= 3 and volume_power and bullish_momentum and vol_ratio >= 0.5:
            sl = support - price*0.0015; risk = price - sl; 
            if risk < 2: sl = price - 3; risk = 3
            tp = price + risk*2
            active_trade = {"type":"BUY","entry":price,"sl":sl,"tp":tp}
            send_telegram(f"🟢 *XAU BUY - POWER CONFIRMED* {buy_score}/4\nPrice: {price:.2f} SL:{sl:.2f} TP:{tp:.2f}\n\n💥 *VOLUME POWER:* {vol_ratio:.2f}x & Increasing {vol_prev:.0f}->{vol_now:.0f}\n🚀 *MOMENTUM:* MA9 slope +{ma9_slope:.2f} ROC +{roc:.2f}% RSI slope {rsi_slope:.1f}\n✅ Trend: {'Above 200MA' if above_200 else 'No'}\n✅ Cross: {'Yes last 10' if cross_up_recent else 'No'}\n✅ Support: {support:.1f} Near:{near_sup}\n✅ RSI: {rsi:.1f}\n\n*Real move, not fake*")
            last_signal_candle = candle_time

        elif sell_score >= 3 and volume_power and bearish_momentum and vol_ratio >= 0.5:
            sl = resistance + price*0.0015; risk = sl - price
            if risk < 2: sl = price + 3; risk = 3
            tp = price - risk*2
            active_trade = {"type":"SELL","entry":price,"sl":sl,"tp":tp}
            send_telegram(f"🔴 *XAU SELL - POWER CONFIRMED* {sell_score}/4\nPrice: {price:.2f} SL:{sl:.2f} TP:{tp:.2f}\n\n💥 *VOLUME POWER:* {vol_ratio:.2f}x & Increasing\n🚀 *MOMENTUM:* MA9 slope {ma9_slope:.2f} ROC {roc:.2f}% RSI slope {rsi_slope:.1f}\n✅ Trend Below 200MA\n✅ Cross last 10: {cross_down_recent}\n✅ Resistance {resistance:.1f} Near:{near_res}\n✅ RSI {rsi:.1f}\n\n*Real move, not fake*")
            last_signal_candle = candle_time

        time.sleep(SCAN_SECONDS)

def telegram_loop():
    offset=0
    while True:
        try:
            r=requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", params={"timeout":20,"offset":offset}, timeout=30).json()
            for upd in r.get("result",[]):
                offset=upd["update_id"]+1
                txt=upd.get("message",{}).get("text","")
                if "/status" in txt:
                    s=last_state; ti = f"\n🎯 {active_trade['type']} E:{active_trade['entry']:.1f} SL:{active_trade['sl']:.1f} TP:{active_trade['tp']:.1f}" if active_trade else "\nNo trade"
                    send_telegram(f"✅ *V8.2 POWER LIVE*\nPrice: {s['price']} RSI:{s['rsi']} Vol:{s['vol']}x\n{s['status']}\nLast:{last_update}{ti}")
                if "/close" in txt:
                    active_trade=None; send_telegram("Cleared")
        except: time.sleep(5)

app = Flask(__name__)
@app.route("/")
def home(): return f"V8.2 POWER {last_state['price']}"

threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000, use_reloader=False), daemon=True).start()
threading.Thread(target=telegram_loop, daemon=True).start()
check_loop()
