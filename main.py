import os, time, threading, requests, math
from flask import Flask
from datetime import datetime
from collections import deque

TOKEN = os.getenv("TELEGRAM_TOKEN","").strip()
CHAT = os.getenv("CHAT_ID","").strip()
PORT = int(os.getenv("PORT", 10000))

RR = 2.0
SL_PIPS = 80
VOL_MA_PERIOD = 20

app = Flask(__name__)
active_trade = None
print(f"=== V9.1.1 POWER MODE 3-SOURCE FIX ===", flush=True)

def send(msg, cid=None):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": str(cid or CHAT), "text": msg, "parse_mode": "Markdown"}, timeout=12)
    except Exception as e: print(f"SEND {e}", flush=True)

def get_gold_3source():
    prices, src = [], {}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    # 1. LBMA
    try:
        r = requests.get("https://api.gold-api.com/price/XAU", headers=headers, timeout=10).json()
        p = float(r['price']); prices.append(p); src['LBMA'] = p
    except Exception as e: print(f"LBMA fail {e}", flush=True)

    # 2. PAXG with header + retry
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=pax-gold&vs_currencies=usd", headers=headers, timeout=12).json()
        if 'pax-gold' in r:
            p = float(r['pax-gold']['usd']); prices.append(p); src['PAXG'] = p
    except Exception as e: print(f"PAXG fail {e}", flush=True)

    # 3. XAUT with header + retry
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=tether-gold&vs_currencies=usd", headers=headers, timeout=12).json()
        if 'tether-gold' in r:
            p = float(r['tether-gold']['usd']); prices.append(p); src['XAUT'] = p
    except Exception as e: print(f"XAUT fail {e}", flush=True)

    avg = sum(prices)/len(prices) if prices else 4128.0
    print(f"3-SRC {src} AVG {avg}", flush=True)
    return avg, src

def get_klines(limit=50):
    try:
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

def check_power_mode():
    closes, volumes = get_klines(50)
    if not closes: return False, "NO DATA", {}
    vol_ma = sum(volumes[-VOL_MA_PERIOD:])/VOL_MA_PERIOD
    vol_now = volumes[-1]; vol_prev = volumes[-2]
    vol_pass = vol_now > vol_ma and vol_now > vol_prev
    ma9_now = ema(closes[-15:], 9); ma9_prev = ema(closes[-16:-1], 9)
    ma9_up = ma9_now > ma9_prev if ma9_now and ma9_prev else False
    ma9_down = ma9_now < ma9_prev if ma9_now and ma9_prev else False
    rsi_now = rsi(closes[-15:]); rsi_prev = rsi(closes[-16:-1])
    rsi_up = rsi_now > rsi_prev; rsi_down = rsi_now < rsi_prev
    roc_now = roc(closes, 5)
    roc_up = roc_now > 0.05; roc_down = roc_now < -0.05
    ema20 = ema(closes, 20); ema50 = ema(closes, 50)
    score_buy = 0; score_sell = 0
    if closes[-1] > ema20: score_buy+=1
    else: score_sell+=1
    if ema20 and ema50 and ema20 > ema50: score_buy+=1
    else: score_sell+=1
    if rsi_now > 50 and rsi_now < 75: score_buy+=1
    elif rsi_now < 50 and rsi_now > 25: score_sell+=1
    if roc_now > 0: score_buy+=1
    else: score_sell+=1
    details = {"vol": f"{vol_now:.1f} > MA {vol_ma:.1f} & prev {vol_prev:.1f} = {'PASS' if vol_pass else 'FAIL'}", "ma9": "UP" if ma9_up else "DOWN", "rsi": f"{rsi_now:.1f}>{rsi_prev:.1f}={'UP' if rsi_up else 'DOWN'}", "roc": f"{roc_now:.3f}%", "sb": score_buy, "ss": score_sell}
    if vol_pass and ma9_up and rsi_up and roc_up and score_buy>=3:
        return True, "BUY", details
    if vol_pass and ma9_down and rsi_down and roc_down and score_sell>=3:
        return True, "SELL", details
    return False, "NO TRADE", details

def build_power_signal(price, src, direction, details):
    sl_dist = SL_PIPS * 0.01; tp_dist = sl_dist * RR
    sl = price - sl_dist if direction=="BUY" else price + sl_dist
    tp = price + tp_dist if direction=="BUY" else price - tp_dist
    src_txt = " | ".join([f"{k} ${v:.2f}" for k,v in src.items()])
    return f"""🚀 *V8.2 POWER MODE SIGNAL*

💰 *${price:,.2f}* ({src_txt})
✅ Vol: {details['vol']}
✅ Mom: MA9 {details['ma9']} RSI {details['rsi']} ROC {details['roc']}
🎯 *{direction}* Entry ${price:.2f} SL ${sl:.2f} TP ${tp:.2f} RR 1:{RR} Conf {details['sb'] if direction=='BUY' else details['ss']}/4
⏰ {datetime.utcnow().strftime('%H:%M UTC')}"""

def track_trades():
    global active_trade
    while True:
        try:
            if active_trade:
                price,_ = get_gold_3source()
                entry=active_trade['entry']; sl=active_trade['sl']; tp=active_trade['tp']; d=active_trade['dir']
                hit=None
                if d=="BUY":
                    if price<=sl: hit="SL"
                    elif price>=tp: hit="TP"
                else:
                    if price>=sl: hit="SL"
                    elif price<=tp: hit="TP"
                if hit:
                    send(f"{'✅ TP HIT!' if hit=='TP' else '❌ SL HIT!'} {d} ${entry:.2f}->{price:.2f} {hit}")
                    active_trade=None
        except: pass
        time.sleep(15)

def bot_loop():
    global active_trade
    try: requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
    except: pass
    time.sleep(2)
    price, src = get_gold_3source()
    send(f"🚀 *V9.1.1 FIXED - 3-SRC*\nPrice ${price:.2f} ({', '.join(src.keys())})\nScanning...")
    while True:
        try:
            price, src = get_gold_3source()
            ok, direction, details = check_power_mode()
            print(f"Scan {price} {direction}", flush=True)
            if ok and not active_trade:
                send(build_power_signal(price, src, direction, details))
                sl_dist=SL_PIPS*0.01; tp_dist=sl_dist*RR
                sl=price-sl_dist if direction=="BUY" else price+sl_dist
                tp=price+tp_dist if direction=="BUY" else price-tp_dist
                active_trade={"dir":direction,"entry":price,"sl":sl,"tp":tp}
        except Exception as e: print(f"Loop {e}", flush=True)
        time.sleep(300)

def listener():
    last_id=0
    while True:
        try:
            r=requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={last_id+1}&timeout=25", timeout=30).json()
            for u in r.get("result", []):
                last_id=u["update_id"]
                if "message" not in u: continue
                txt=u["message"].get("text",""); cid=u["message"]["chat"]["id"]; low=txt.lower()
                if "/price" in low:
                    p,s=get_gold_3source(); st="\n".join([f"{k}: ${v:.2f}" for k,v in s.items()])
                    send(f"💰 *3-Source*\n{st}\n\n*AVG ${p:.2f}* Sources {len(s)}/3", cid)
                elif "/scan" in low:
                    p,s=get_gold_3source(); ok, direction, d=check_power_mode()
                    send(f"🔍 *SCAN* ${p:.2f}\n{direction}\nVol {d['vol']}\nMom {d['ma9']} {d['rsi']} {d['roc']}\nB:{d['sb']} S:{d['ss']}", cid)
                elif "/status" in low:
                    p,s=get_gold_3source(); tr=f"{active_trade['dir']} @ {active_trade['entry']:.2f}" if active_trade else "None"
                    send(f"✅ V9.1.1\n${p:.2f} {len(s)}/3 src\nActive {tr}\nRR 1:{RR}", cid)
                elif "/start" in low:
                    send("🚀 *V9.1.1*\n/price /scan /status", cid)
        except: time.sleep(5)
        time.sleep(2)

@app.route("/")
def home():
    p,s=get_gold_3source()
    return f"V9.1.1 ${p} {s}"

threading.Thread(target=bot_loop, daemon=True).start()
threading.Thread(target=track_trades, daemon=True).start()
threading.Thread(target=listener, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
