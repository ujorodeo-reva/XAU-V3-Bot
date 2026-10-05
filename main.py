import os, time, threading, requests, yfinance as yf, pandas as pd
from flask import Flask
from datetime import datetime

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYMBOL = "GC=F"
SCAN_SECONDS = 60
VOL_MULT = 0.10

last_state = {"price":0,"rsi":0,"vol":0,"ma200":0,"status":"starting"}
last_update = "never"
active_trade = None  # {type, entry, sl, tp, time}
last_signal_candle = None

def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

def rsi_calc(s, p=14):
    d = s.diff(); g = d.clip(lower=0).ewm(alpha=1/p, adjust=False).mean()
    l = -d.clip(upper=0).ewm(alpha=1/p, adjust=False).mean()
    return 100 - (100/(1+g/l.replace(0,0.00001)))

def send_telegram(t):
    try: requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={"chat_id":CHAT_ID,"text":t,"parse_mode":"Markdown"}, timeout=15)
    except Exception as e: log(f"TG err {e}")

def fetch():
    try:
        df = yf.download(SYMBOL, period="6mo", interval="15m", progress=False, auto_adjust=True)
        if df.empty or len(df) < 210: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df["rsi"]=rsi_calc(df["Close"]); df["ma9"]=df["Close"].rolling(9).mean()
        df["ma20"]=df["Close"].rolling(20).mean(); df["ma200"]=df["Close"].rolling(200).mean()
        df["vol_ma20"]=df["Volume"].rolling(20).mean()
        return df
    except Exception as e:
        if "429" in str(e): time.sleep(120)
        return None

def detect_sr(df):
    recent = df.tail(50)
    sup = recent.nsmallest(3,"Low")["Low"].mean()
    res = recent.nlargest(3,"High")["High"].mean()
    return sup, res

def check_loop():
    global last_state, last_update, active_trade, last_signal_candle
    log("V7 TP/SL Bot started")
    time.sleep(5)
    while True:
        df = fetch()
        if df is None:
            time.sleep(30); continue

        last = df.iloc[-1]; prev1=df.iloc[-2]; prev2=df.iloc[-3]; prev3=df.iloc[-4]
        price = float(last["Close"]); rsi=float(last["rsi"])
        ma9=float(last["ma9"]); ma20=float(last["ma20"]); ma200=float(last["ma200"])
        vol_ma=float(last["vol_ma20"]) if pd.notna(last["vol_ma20"]) else 0
        vol_ratio = 1.0 if vol_ma < 1 else float(last["Volume"])/vol_ma
        if vol_ratio < 0.05: vol_ratio = 1.0

        support, resistance = detect_sr(df)
        near_sup = abs(price-support)/price < 0.003
        near_res = abs(price-resistance)/price < 0.003
        cross_up = ma9>ma20 and (prev1["ma9"]<=prev1["ma20"] or prev2["ma9"]<=prev2["ma20"] or prev3["ma9"]<=prev3["ma20"])
        cross_down = ma9<ma20 and (prev1["ma9"]>=prev1["ma20"] or prev2["ma9"]>=prev2["ma20"] or prev3["ma9"]>=prev3["ma20"])

        last_state = {"price":round(price,2),"rsi":round(rsi,2),"vol":round(vol_ratio,2),"ma200":round(ma200,2),"status":f"{'ABOVE' if price>ma200 else 'BELOW'}200"}
        last_update = datetime.now().strftime("%H:%M:%S")

        # ===== 1. CHECK ACTIVE TRADE FOR TP/SL =====
        if active_trade:
            entry = active_trade["entry"]; sl = active_trade["sl"]; tp = active_trade["tp"]; typ = active_trade["type"]
            if typ == "BUY":
                if price >= tp:
                    send_telegram(f"✅ *TP HIT - BUY WIN* 🎯\nEntry: {entry:.2f}\nTP: {tp:.2f}\nNow: {price:.2f}\nProfit: +{price-entry:.2f}\nTime: {last_update}")
                    active_trade = None
                elif price <= sl:
                    send_telegram(f"❌ *SL HIT - BUY LOSS*\nEntry: {entry:.2f}\nSL: {sl:.2f}\nNow: {price:.2f}\nLoss: {price-entry:.2f}\nTime: {last_update}")
                    active_trade = None
            else: # SELL
                if price <= tp:
                    send_telegram(f"✅ *TP HIT - SELL WIN* 🎯\nEntry: {entry:.2f}\nTP: {tp:.2f}\nNow: {price:.2f}\nProfit: +{entry-price:.2f}\nTime: {last_update}")
                    active_trade = None
                elif price >= sl:
                    send_telegram(f"❌ *SL HIT - SELL LOSS*\nEntry: {entry:.2f}\nSL: {sl:.2f}\nNow: {price:.2f}\nLoss: {entry-price:.2f}\nTime: {last_update}")
                    active_trade = None

            # If still in trade, log and skip new signals
            if active_trade:
                log(f"In TRADE {typ} Entry:{entry:.1f} SL:{sl:.1f} TP:{tp:.1f} Now:{price:.1f} PnL:{price-entry if typ=='BUY' else entry-price:.1f}")
                time.sleep(SCAN_SECONDS); continue

        # ===== 2. LOOK FOR NEW SIGNAL (only if no active trade) =====
        candle_time = str(df.index[-1])
        if candle_time == last_signal_candle:
            time.sleep(SCAN_SECONDS); continue

        log(f"{price:.1f} RSI:{rsi:.1f} 9:{ma9:.1f} 20:{ma20:.1f} 200:{ma200:.1f} Sup:{support:.1f} Res:{resistance:.1f} Vol:{vol_ratio:.2f}x")

        if price>ma200 and cross_up and near_sup and vol_ratio>=VOL_MULT and rsi<45:
            sl = support - (price*0.0015)  # SL 0.15% below support
            risk = price - sl
            tp = price + (risk*2)  # 1:2 RR
            active_trade = {"type":"BUY","entry":price,"sl":sl,"tp":tp,"time":last_update}
            send_telegram(f"🟢 *XAU BUY - FULL CONFLUENCE*\nEntry: {price:.2f}\nSL: {sl:.2f} (-{risk:.2f})\nTP: {tp:.2f} (+{risk*2:.2f})\n✅ Above 200MA\n✅ 9MA crossed ABOVE 20MA\n✅ At SUPPORT {support:.1f}\n✅ RSI {rsi:.1f} Vol {vol_ratio:.2f}x\n*Tracking TP/SL now...*")
            last_signal_candle = candle_time

        elif price<ma200 and cross_down and near_res and vol_ratio>=VOL_MULT and rsi>55:
            sl = resistance + (price*0.0015)
            risk = sl - price
            tp = price - (risk*2)
            active_trade = {"type":"SELL","entry":price,"sl":sl,"tp":tp,"time":last_update}
            send_telegram(f"🔴 *XAU SELL - FULL CONFLUENCE*\nEntry: {price:.2f}\nSL: {sl:.2f} (+{risk:.2f})\nTP: {tp:.2f} (-{risk*2:.2f})\n✅ Below 200MA\n✅ 9MA crossed BELOW 20MA\n✅ At RESISTANCE {resistance:.1f}\n✅ RSI {rsi:.1f} Vol {vol_ratio:.2f}x\n*Tracking TP/SL now...*")
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
                    s=last_state
                    trade_info = f"\n🎯 ACTIVE: {active_trade['type']} Entry {active_trade['entry']:.1f} SL {active_trade['sl']:.1f} TP {active_trade['tp']:.1f}" if active_trade else "\nNo active trade"
                    send_telegram(f"✅ *XAU V7 LIVE*\nPrice: {s['price']} RSI: {s['rsi']}\n200MA: {s['ma200']} Vol: {s['vol']}x\nLast: {last_update}{trade_info}")
                if "/close" in txt:
                    active_trade=None
                    send_telegram("Trade tracking cleared")
        except: time.sleep(5)

app = Flask(__name__)
@app.route("/")
def home(): return f"V7 OK {last_state['price']} Active:{active_trade['type'] if active_trade else 'None'}"

threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000, use_reloader=False), daemon=True).start()
threading.Thread(target=telegram_loop, daemon=True).start()
check_loop()
