import yfinance as yf
import pandas as pd
import time
import requests
import os
from datetime import datetime
from flask import Flask
import threading

app = Flask(__name__)
@app.route('/')
def home():
    return "XAU V3 5m + S/R Bot LIVE!"
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
threading.Thread(target=run_flask, daemon=True).start()

SYMBOL = "GC=F"
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN","").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID","").strip()

last_state = {"price":0,"support":0,"resistance":0,"rsi":0,"vol":0,"ema9":0,"ema20":0,"ema200":0,"near_sup":False,"near_res":False,"last_update":"Never","status":"Starting..."}

def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id":CHAT_ID,"text":msg}, timeout=10)
    except:
        pass

def get_sr(df):
    try:
        recent = df.tail(50)
        sup = float(recent['Low'].min())
        res = float(recent['High'].max())
        return sup,res
    except:
        return 0,0

def rsi_calc(series, period=14):
    delta = series.diff()
    gain = delta.where(delta>0,0).rolling(period).mean()
    loss = -delta.where(delta<0,0).rolling(period).mean()
    rs = gain/loss
    rsi = 100 - (100/(1+rs))
    return rsi

def fetch_data():
    for _ in range(3):
        try:
            df = yf.download(SYMBOL, period="5d", interval="5m", progress=False, auto_adjust=False)
            if df is not None and not df.empty and len(df)>100:
                df = df.dropna()
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                return df
        except Exception as e:
            print(f"fetch retry: {e}")
        time.sleep(5)
    return None

def check_signal():
    df = fetch_data()
    if df is None or len(df)<200:
        print("No data, retry")
        last_state["status"]="Waiting data"
        return
    df['EMA200'] = df['Close'].ewm(span=200).mean()
    df['EMA9'] = df['Close'].ewm(span=9).mean()
    df['EMA20'] = df['Close'].ewm(span=20).mean()
    df['RSI'] = rsi_calc(df['Close'])
    df['RSI_DELTA'] = df['RSI'].diff()
    df['VOL_AVG'] = df['Volume'].rolling(20).mean()
    df['VOL_RATIO'] = df['Volume']/df['VOL_AVG']
    ema12 = df['Close'].ewm(span=12).mean()
    ema26 = df['Close'].ewm(span=26).mean()
    df['MACD'] = ema12-ema26
    df['MACD_SIG'] = df['MACD'].ewm(span=9).mean()

    last = df.iloc[-1]
    prev = df.iloc[-2]
    close = float(last['Close'])
    support,resistance = get_sr(df)
    ema200 = float(last['EMA200'])
    ema9 = float(last['EMA9'])
    ema20 = float(last['EMA20'])
    rsi = float(last['RSI']) if pd.notna(last['RSI']) else 50
    rsi_delta = float(last['RSI_DELTA']) if pd.notna(last['RSI_DELTA']) else 0
    macd_line = float(last['MACD'])
    macd_sig = float(last['MACD_SIG'])
    vol_ratio = float(last['VOL_RATIO']) if pd.notna(last['VOL_RATIO']) else 1.0

    dist_ema = abs(close-ema200)/ema200 if ema200!=0 else 1
    ema_filter = dist_ema <= 0.007
    vol_filter = 1.25 <= vol_ratio <= 1.70
    cross_up = prev['EMA9'] < prev['EMA20'] and last['EMA9'] > last['EMA20']
    cross_down = prev['EMA9'] > prev['EMA20'] and last['EMA9'] < last['EMA20']
    near_sup = abs(close-support)/close <= 0.005 if close!=0 else False
    near_res = abs(close-resistance)/close <= 0.005 if close!=0 else False

    last_state.update({"price":close,"support":support,"resistance":resistance,"rsi":rsi,"vol":vol_ratio,"ema9":ema9,"ema20":ema20,"ema200":ema200,"near_sup":near_sup,"near_res":near_res,"last_update":datetime.now().strftime("%H:%M:%S"),"status":"Scanning"})

    long_cond = close>ema200 and ema_filter and cross_up and (35<rsi<68 and rsi_delta>3) and (macd_line>macd_sig) and vol_filter and near_sup
    short_cond = close<ema200 and ema_filter and cross_down and (32<rsi<65 and rsi_delta<-3) and (macd_line<macd_sig) and vol_filter and near_res

    print(f"[{last_state['last_update']}] {close:.2f} RSI:{rsi:.1f} Vol:{vol_ratio:.2f}x S:{support:.2f} R:{resistance:.2f}")

    if long_cond:
        sl = close*0.996
        tp = close*1.008
        msg = f"LONG XAU 5m\nPrice {close:.2f}\nSup {support:.2f} OK\nTP {tp:.2f} SL {sl:.2f}\nCOMMAND: BUY XAUUSD {close:.2f} SL {sl:.2f} TP {tp:.2f}"
        send_telegram(msg)
        last_state["status"]=f"LONG sent {close:.2f}"
    if short_cond:
        sl = close*1.004
        tp = close*0.992
        msg = f"SHORT XAU 5m\nPrice {close:.2f}\nRes {resistance:.2f} OK\nTP {tp:.2f} SL {sl:.2f}\nCOMMAND: SELL XAUUSD {close:.2f} SL {sl:.2f} TP {tp:.2f}"
        send_telegram(msg)
        last_state["status"]=f"SHORT sent {close:.2f}"

def telegram_listener():
    offset=0
    print("Telegram listener started")
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=10"
            r = requests.get(url, timeout=15).json()
            if not r.get("ok"):
                time.sleep(3)
                continue
            for upd in r.get("result",[]):
                offset = upd["update_id"]+1
                msg_obj = upd.get("message",{})
                text = msg_obj.get("text","").strip()
                cid = str(msg_obj.get("chat",{}).get("id",""))
                if cid!= str(CHAT_ID):
                    continue
                if text=="/status":
                    txt = f"XAU V3 STATUS\nPrice: {last_state['price']:.2f}\nSupport: {last_state['support']:.2f} {'NEAR' if last_state['near_sup'] else 'Far'}\nResistance: {last_state['resistance']:.2f} {'NEAR' if last_state['near_res'] else 'Far'}\nEMA9: {last_state['ema9']:.2f} EMA20: {last_state['ema20']:.2f} EMA200: {last_state['ema200']:.2f}\nRSI: {last_state['rsi']:.1f} Vol: {last_state['vol']:.2f}x\nStatus: {last_state['status']}\nLast: {last_state['last_update']}\nBot LIVE"
                    send_telegram(txt)
                elif text=="/price":
                    send_telegram(f"XAU Price: {last_state['price']:.2f} S:{last_state['support']:.2f} R:{last_state['resistance']:.2f} {last_state['last_update']}")
                elif text=="/help":
                    send_telegram("/status - status\n/price - price\n/help - help")
        except Exception as e:
            print(f"listener err {e}")
        time.sleep(2)

threading.Thread(target=telegram_listener, daemon=True).start()
print("Bot started...")
send_telegram("XAU V3 Bot LIVE! Type /status")
while True:
    try:
        check_signal()
    except Exception as e:
        print(f"loop err {e}")
    time.sleep(60)
