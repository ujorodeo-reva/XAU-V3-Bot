import os, time, threading, requests, math
from flask import Flask
from datetime import datetime
from collections import deque

TOKEN = os.getenv("TELEGRAM_TOKEN","").strip()
CHAT = os.getenv("CHAT_ID","").strip()
PORT = int(os.getenv("PORT", 10000))

# === SETTINGS ===
RR = 2.0
SL_PIPS = 80  # $0.80
VOL_MA_PERIOD = 20
# ================

app = Flask(__name__)
active_trade = None  # {'dir': 'BUY', 'entry': 3912, 'sl': ..., 'tp': ..., 'time': ...}
print(f"=== V9.1 POWER MODE RR 1:{RR} ===", flush=True)

def send(msg, cid=None):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": str(cid or CHAT), "text": msg, "parse_mode": "Markdown"}, timeout=12)
    except Exception as e: print(f"SEND {e}", flush=True)

# --- 3-SOURCE EXACT PRICE ---
def get_gold_3source():
    prices, src = [], {}
    try:
        r = requests.get("https://api.gold-api.com/price/XAU", timeout=8).json()
        p = float(r['price']); prices.append(p); src['LBMA'] = p
    except: pass
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=pax-gold&vs_currencies=usd", timeout=8).json()
        p = float(r['pax-gold']['usd']); prices.append(p); src['PAXG'] = p
    except: pass
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=tether-gold&vs_currencies=usd", timeout=8).json()
        p = float(r['tether-gold']['usd']); prices.append(p); src['XAUT'] = p
    except: pass
    avg = sum(prices)/len(prices) if prices else 3912.0
    return avg, src

# --- MARKET DATA FOR VOLUME & MOMENTUM (using PAXG as XAU proxy with volume) ---
def get_klines(limit=50):
    try:
        # PAXGUSDT has real volume - best proxy for gold volume surge
        url = f"https://api.binance.com/api/v3/klines?symbol=PAXGUSDT&interval=5m&limit={limit}"
        data = requests.get(url, timeout=10).json()
        closes = [float(k[4]) for k in data]
        volumes = [float(k[5]) for k in data]
        return closes, volumes
    except Exception as e:
        print(f"Klines fail {e}", flush=True)
        return None, None

def ema(data, period):
    if len(data) < period: return None
    k = 2/(period+1)
    ema_val = sum(data[:period])/period
    for price in data[period:]: ema_val = price*k + ema_val*(1-k)
    return ema_val

def rsi(data, period=14):
    if len(data) < period+1: return 50
    gains, losses = [], []
    for i in range(1, len(data)):
        diff = data[i]-data[i-1]
        gains.append(max(0,diff)); losses.append(max(0,-diff))
    avg_gain = sum(gains[-period:])/period
    avg_loss = sum(losses[-period:])/period
    if avg_loss == 0: return 100
    rs = avg_gain/avg_loss
    return 100 - (100/(1+rs))

def roc(data, period=5):
    if len(data) <= period: return 0
    return ((data[-1]-data[-period-1])/data[-period-1])*100

# --- V8.2 MANDATORY FILTERS ---
def check_power_mode():
    closes, volumes = get_klines(50)
    if not closes: return False, "No klines", {}

    # 1. MANDATORY: VOLUME SURGE + INCREASING
    vol_ma = sum(volumes[-VOL_MA_PERIOD:])/VOL_MA_PERIOD
    vol_now = volumes[-1]
    vol_prev = volumes[-2]
    vol_surge = vol_now > vol_ma
    vol_increasing = vol_now > vol_prev
    vol_pass = vol_surge and vol_increasing

    # 2. MANDATORY: MOMENTUM PUSHING THAT DIRECTION
    ma9_now = ema(closes[-15:], 9)
    ma9_prev = ema(closes[-16:-1], 9)
    ma9_slope_up = ma9_now > ma9_prev if ma9_now and ma9_prev else False
    ma9_slope_down = ma9_now < ma9_prev if ma9_now and ma9_prev else False

    rsi_now = rsi(closes[-15:])
    rsi_prev = rsi(closes[-16:-1])
    rsi_slope_up = rsi_now > rsi_prev
    rsi_slope_down = rsi_now < rsi_prev

    roc_now = roc(closes, 5)
    roc_up = roc_now > 0.05  # >0.05% pushing up
    roc_down = roc_now < -0.05

    momentum_buy = ma9_slope_up and rsi_slope_up and roc_up
    momentum_sell = ma9_slope_down and rsi_slope_down and roc_down

    # 3/4 OTHER CONFIRMATIONS
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    score_buy = 0
    score_sell = 0
    if closes[-1] > ema20: score_buy +=1
    else: score_sell +=1
    if ema20 and ema50 and ema20 > ema50: score_buy +=1
    else: score_sell +=1
    if rsi_now > 50 and rsi_now < 75: score_buy +=1
    elif rsi_now < 50 and rsi_now > 25: score_sell +=1
    if roc_now > 0: score_buy +=1
    else: score_sell +=1

    details = {
        "vol": f"{vol_now:.1f} vs MA20 {vol_ma:.1f} prev {vol_prev:.1f} -> {'PASS' if vol_pass else 'FAIL'}",
        "ma9_slope": f"{'UP' if ma9_slope_up else 'DOWN'}",
        "rsi_slope": f"{rsi_now:.1f} vs {rsi_prev:.1f} -> {'UP' if rsi_slope_up else 'DOWN'}",
        "roc": f"{roc_now:.3f}%",
        "score_buy": score_buy,
        "score_sell": score_sell
    }

    if vol_pass and momentum_buy and score_buy >=3:
        return True, "BUY", details
    if vol_pass and momentum_sell and score_sell >=3:
        return True, "SELL", details

    return False, "NO TRADE", details

def build_power_signal(price, src, direction, details):
    sl_dist = SL_PIPS * 0.01
    tp_dist = sl_dist * RR
    if direction == "BUY":
        sl = price - sl_dist; tp = price + tp_dist
    else:
        sl = price + sl_dist; tp = price - tp_dist

    src_txt = " | ".join([f"{k} ${v:.2f}" for k,v in src.items()])
    return f"""🚀 *V8.2 POWER MODE SIGNAL*

💰 *${price:,.2f}* ({src_txt})

✅ *MANDATORY PASS:*
• Volume SURGE: {details['vol']}
• Momentum: MA9 {details['ma9_slope']} + RSI {details['rsi_slope']} + ROC {details['roc']}

🎯 *{direction}*
Entry: ${price:,.2f}
SL: ${sl:,.2f} (-{SL_PIPS} pips)
TP: ${tp:,.2f} (+{SL_PIPS*RR:.0f} pips) RR 1:{RR}
Confirmations: {details['score_buy'] if direction=='BUY' else details['score_sell']}/4

⏰ {datetime.utcnow().strftime('%H:%M UTC')}
Bot tracking TP/SL now...
"""

# --- TRADE TRACKER ---
def track_trades():
    global active_trade
    while True:
        try:
            if active_trade:
                price, _ = get_gold_3source()
                entry = active_trade['entry']; sl = active_trade['sl']; tp = active_trade['tp']; direction = active_trade['dir']
                hit = None
                if direction == "BUY":
                    if price <= sl: hit = "SL"
                    elif price >= tp: hit = "TP"
                else:
                    if price >= sl: hit = "SL"
                    elif price <= tp: hit = "TP"
                
                if hit:
                    pnl = (tp-entry) if direction=="BUY" else (entry-tp)
                    if hit=="SL": pnl = -abs(entry-sl)
                    send(f"{'✅ TP HIT!' if hit=='TP' else '❌ SL HIT!'}\n\n{active_trade['dir']} ${entry:.2f} -> ${price:.2f}\nPnL: ${pnl:.2f} RR 1:{RR}\n⏰ {datetime.utcnow().strftime('%H:%M UTC')}")
                    active_trade = None
        except Exception as e: print(f"Tracker {e}", flush=True)
        time.sleep(15)

def bot_loop():
    global active_trade
    try: requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
    except: pass
    time.sleep(2)
    price, src = get_gold_3source()
    send(f"🚀 *V8.2 POWER MODE LIVE*\n\n✅ Vol >20MA + Increasing MANDATORY\n✅ Momentum MA9+RSI+ROC MANDATORY\n✅ 3/4 confirmations\n✅ Tracker ON\n✅ 3-source exact price\n✅ RR 1:{RR}\n\nPrice: ${price:.2f} ({', '.join(src.keys())})\nScanning 5m...")
    while True:
        try:
            price, src = get_gold_3source()
            ok, direction, details = check_power_mode()
            print(f"Scan {price} {direction} {details}", flush=True)
            if ok and not active_trade:
                msg = build_power_signal(price, src, direction, details)
                send(msg)
                sl_dist = SL_PIPS*0.01; tp_dist = sl_dist*RR
                sl = price - sl_dist if direction=="BUY" else price + sl_dist
                tp = price + tp_dist if direction=="BUY" else price - tp_dist
                active_trade = {"dir": direction, "entry": price, "sl": sl, "tp": tp, "time": datetime.utcnow()}
        except Exception as e: print(f"Loop {e}", flush=True)
        time.sleep(300) # 5 min scan

def listener():
    last_id = 0
    while True:
        try:
            r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={last_id+1}&timeout=25", timeout=30).json()
            for u in r.get("result", []):
                last_id = u["update_id"]
                if "message" not in u: continue
                txt = u["message"].get("text",""); cid = u["message"]["chat"]["id"]; low=txt.lower()
                if "/price" in low:
                    p,s = get_gold_3source(); st="\n".join([f"{k}: ${v:.2f}" for k,v in s.items()])
                    send(f"💰 *3-Source*\n{st}\nAVG ${p:.2f}", cid)
                elif "/scan" in low or "/power" in low:
                    p,s = get_gold_3source(); ok, direction, d = check_power_mode()
                    send(f"🔍 *POWER SCAN*\nPrice ${p:.2f}\nResult: {direction}\nVol: {d['vol']}\nMA9: {d['ma9_slope']} RSI: {d['rsi_slope']} ROC: {d['roc']}\nScore B:{d['score_buy']} S:{d['score_sell']}/4", cid)
                elif "/status" in low:
                    p,s = get_gold_3source(); tr = f"{active_trade['dir']} @ ${active_trade['entry']:.2f}" if active_trade else "No active trade"
                    send(f"✅ *V8.2 POWER*\nPrice ${p:.2f}\nRR 1:{RR}\nActive: {tr}\nSources: {len(s)}/3", cid)
                elif "/start" in low:
                    send("🚀 *V8.2 POWER MODE*\n\nMandatory:\n1. Vol >20MA + increasing\n2. MA9 slope + RSI slope + ROC push\nThen 3/4 confirms\n\n/price /scan /status", cid)
        except: time.sleep(5)
        time.sleep(2)

@app.route("/")
def home():
    p,s = get_gold_3source()
    return f"V9.1 POWER MODE ${p} {s} trade {active_trade}"

threading.Thread(target=bot_loop, daemon=True).start()
threading.Thread(target=track_trades, daemon=True).start()
threading.Thread(target=listener, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
