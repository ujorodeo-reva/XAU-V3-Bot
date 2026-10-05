import os, time, threading, requests
from flask import Flask
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PORT = int(os.getenv("PORT", 10000))
SYMBOL = "PAXGUSDT"
INTERVAL = "1m"
SL_PERCENT = 0.006
TP_PERCENT = 0.012

app = Flask(__name__)
active_trade=None
last_price=0
last_rsi=0
last_update="Never"
last_update_id=0

def send_telegram(msg, chat_id=None):
    try:
        cid = chat_id if chat_id else CHAT_ID
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": cid, "text": msg}, timeout=10)
    except: pass

def init_telegram():
    try:
        requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
        send_telegram("V8.5 BOOTING - /status listener active")
    except: pass

def get_klines():
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval={INTERVAL}&limit=100"
        r = requests.get(url, timeout=10).json()
        return [float(x[4]) for x in r], [float(x[5]) for x in r]
    except:
        try:
            url = "https://www.okx.com/api/v5/market/candles?instId=PAXG-USDT&bar=1m&limit=100"
            r = requests.get(url, timeout=10).json()
            data = r['data'][::-1]
            return [float(x[4]) for x in data], [float(x[5]) for x in data]
        except: return None, None

def calc_ema(prices, p):
    ema=prices[0]; k=2/(p+1)
    for x in prices[1:]: ema=x*k+ema*(1-k)
    return ema
def calc_rsi(prices, per=14):
    g=[]; l=[]
    for i in range(1,len(prices)):
        d=prices[i]-prices[i-1]
        g.append(max(d,0)); l.append(max(-d,0))
    if len(g)<per: return 50
    ag=sum(g[-per:])/per; al=sum(l[-per:])/per
    if al==0: return 70
    return 100-(100/(1+ag/al))

def check_signal():
    global last_price, last_rsi, last_update, active_trade
    closes, volumes = get_klines()
    if not closes: return
    price=closes[-1]; last_price=price; last_update=datetime.now().strftime("%H:%M:%S")
    ema9=calc_ema(closes[-21:],9); ema21=calc_ema(closes[-21:],21); ema20=calc_ema(closes[-20:],20)
    rsi=calc_rsi(closes,14); last_rsi=rsi
    roc=((closes[-1]-closes[-6])/closes[-6])*100 if len(closes)>6 else 0
    avg_vol=sum(volumes[-20:-1])/19 if len(volumes)>20 else volumes[-1]
    if active_trade:
        e=active_trade['entry']; t=active_trade['type']; tp=active_trade['tp']; sl=active_trade['sl']
        if t=="BUY":
            if price>=tp: send_telegram(f"✅ TP HIT BUY +1.2% {price:.2f}"); active_trade=None
            elif price<=sl: send_telegram(f"❌ SL HIT BUY -0.6% {price:.2f}"); active_trade=None
        else:
            if price<=tp: send_telegram(f"✅ TP HIT SELL +1.2% {price:.2f}"); active_trade=None
            elif price>=sl: send_telegram(f"❌ SL HIT SELL -0.6% {price:.2f}"); active_trade=None
        return
    vol_surge=volumes[-1]>avg_vol*1.2; vol_inc=volumes[-1]>volumes[-2]
    if not (vol_surge and vol_inc): return
    prev_rsi=calc_rsi(closes[:-1],14)
    score=0
    if price>ema20: score+=1
    if ema9>ema21: score+=1
    if 35<rsi<70 and rsi>prev_rsi: score+=1
    if roc>0.05: score+=1
    if score>=3:
        tp=price*(1+TP_PERCENT); sl=price*(1-SL_PERCENT)
        active_trade={"type":"BUY","entry":price,"tp":tp,"sl":sl}
        send_telegram(f"🟢 BUY V8.5 1:2 {price:.2f} RSI {rsi:.1f} Score {score}/4 TP {tp:.2f} SL {sl:.2f}"); return
    score=0
    if price<ema20: score+=1
    if ema9<ema21: score+=1
    if 30<rsi<65 and rsi<prev_rsi: score+=1
    if roc<-0.05: score+=1
    if score>=3:
        tp=price*(1-TP_PERCENT); sl=price*(1+SL_PERCENT)
        active_trade={"type":"SELL","entry":price,"tp":tp,"sl":sl}
        send_telegram(f"🔴 SELL V8.5 1:2 {price:.2f} RSI {rsi:.1f} Score {score}/4 TP {tp:.2f} SL {sl:.2f}")

def telegram_listener():
    global last_update_id
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id+1}&timeout=10"
            r = requests.get(url, timeout=15).json()
            if "result" in r and len(r["result"])>0:
                for upd in r["result"]:
                    last_update_id = upd["update_id"]
                    if "message" in upd and "text" in upd["message"]:
                        text = upd["message"]["text"].lower()
                        cid = upd["message"]["chat"]["id"]
                        # handle /status, /status@botname, status
                        if "status" in text or "price" in text:
                            if active_trade:
                                ti = f"{active_trade['type']} Entry {active_trade['entry']:.2f}"
                            else:
                                ti = "No active trade - hunting"
                            reply = f"✅ V8.5 POWER 1:2\nPrice: {last_price:.2f}\nRSI: {last_rsi:.2f}\nLast: {last_update}\nTrade: {ti}\nRR 1:2"
                            send_telegram(reply, cid)
        except: pass
        time.sleep(2)

def bot_loop():
    init_telegram()
    time.sleep(2)
    send_telegram(f"✅ XAU V8.5 LIVE 1:2 RR\nSend /status here - I will reply now")
    while True:
        try: check_signal()
        except: pass
        time.sleep(60)

@app.route("/")
def home(): return "V8.5 LIVE 1:2 - /status works"

@app.route("/status")
def st():
    ti = str(active_trade) if active_trade else "No trade - hunting"
    return f"V8.5 {last_price} RSI {last_rsi} {last_update} {ti}"

threading.Thread(target=bot_loop, daemon=True).start()
threading.Thread(target=telegram_listener, daemon=True).start()

if __name__=="__main__": app.run(host="0.0.0.0", port=PORT)
