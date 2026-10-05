import os
import time
import threading
import requests
from flask import Flask
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PORT = int(os.getenv("PORT", 10000))

SYMBOL = "PAXGUSDT"
INTERVAL = "1m"
SL_PERCENT = 0.006
TP_PERCENT = 0.012 # 1:2

app = Flask(__name__)
active_trade = None
last_price = 0
last_rsi = 0
last_update = "Never"
last_telegram_update_id = 0

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except: pass

def get_klines():
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval={INTERVAL}&limit=100"
        r = requests.get(url, timeout=10).json()
        closes = [float(x[4]) for x in r]
        volumes = [float(x[5]) for x in r]
        return closes, volumes
    except:
        try:
            url = f"https://www.okx.com/api/v5/market/candles?instId=PAXG-USDT&bar={INTERVAL}&limit=100"
            r = requests.get(url, timeout=10).json()
            data = r['data'][::-1]
            closes = [float(x[4]) for x in data]
            volumes = [float(x[5]) for x in data]
            return closes, volumes
        except: return None, None

def calc_ema(prices, period):
    ema = prices[0]
    k = 2/(period+1)
    for p in prices[1:]: ema = p*k + ema*(1-k)
    return ema

def calc_rsi(prices, period=14):
    gains=[]; losses=[]
    for i in range(1,len(prices)):
        d=prices[i]-prices[i-1]
        gains.append(max(d,0)); losses.append(max(-d,0))
    if len(gains)<period: return 50
    ag=sum(gains[-period:])/period; al=sum(losses[-period:])/period
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
    vol_surge=volumes[-1]>avg_vol*1.2; vol_inc=volumes[-1]>volumes[-2]

    if active_trade:
        e=active_trade['entry']; t=active_trade['type']; tp=active_trade['tp']; sl=active_trade['sl']
        if t=="BUY":
            if price>=tp: send_telegram(f"✅ TP HIT BUY (1:2)\n+{price-e:.2f} (+1.2%)"); active_trade=None
            elif price<=sl: send_telegram(f"❌ SL HIT BUY\n{price-e:.2f}"); active_trade=None
        else:
            if price<=tp: send_telegram(f"✅ TP HIT SELL (1:2)\n+{e-price:.2f} (+1.2%)"); active_trade=None
            elif price>=sl: send_telegram(f"❌ SL HIT SELL\n{e-price:.2f}"); active_trade=None
        return

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
        send_telegram(f"🟢 BUY V8.4 POWER 1:2\nPrice {price:.2f}\nRSI {rsi:.1f}↑ ROC {roc:.2f}% Score {score}/4\nTP {tp:.2f} (+1.2%) SL {sl:.2f} (-0.6%)")
        return
    score=0
    if price<ema20: score+=1
    if ema9<ema21: score+=1
    if 30<rsi<65 and rsi<prev_rsi: score+=1
    if roc<-0.05: score+=1
    if score>=3:
        tp=price*(1-TP_PERCENT); sl=price*(1+SL_PERCENT)
        active_trade={"type":"SELL","entry":price,"tp":tp,"sl":sl}
        send_telegram(f"🔴 SELL V8.4 POWER 1:2\nPrice {price:.2f}\nRSI {rsi:.1f}↓ ROC {roc:.2f}% Score {score}/4\nTP {tp:.2f} (-1.2%) SL {sl:.2f} (+0.6%)")

def telegram_command_listener():
    global last_telegram_update_id
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_telegram_update_id+1}&timeout=20"
            r = requests.get(url, timeout=25).json()
            if "result" in r:
                for update in r["result"]:
                    last_telegram_update_id = update["update_id"]
                    if "message" in update and "text" in update["message"]:
                        txt = update["message"]["text"].strip().lower()
                        if txt in ["/status", "status", "/price", "/info"]:
                            trade_info = "No active trade - hunting" if not active_trade else f"{active_trade['type']} Entry {active_trade['entry']:.2f} TP {active_trade['tp']:.2f} SL {active_trade['sl']:.2f}"
                            reply = f"✅ V8.4 POWER 1:2\nPrice: {last_price:.2f}\nRSI: {last_rsi:.2f}\nLast Check: {last_update}\nTrade: {trade_info}\nRR: 1:2 (0.6% SL / 1.2% TP)"
                            send_telegram(reply)
                        elif txt in ["/help", "help"]:
                            send_telegram("Commands:\n/status - current price & trade\n/price - same as status")
        except: pass
        time.sleep(3)

def bot_loop():
    send_telegram("✅ XAU V8.4 POWER LIVE - 1:2 RR + /status reply\nSL 0.6% | TP 1.2% | Send /status in Telegram")
    while True:
        try: check_signal()
        except: pass
        time.sleep(60)

@app.route("/")
def home(): return f"V8.4 1:2 LIVE | {last_price:.2f} RSI {last_r
