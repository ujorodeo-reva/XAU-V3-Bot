import yfinance as yf
import pandas as pd
import ta
import time
import requests
import os
from datetime import datetime

SYMBOL = "GC=F"
TIMEFRAME = "15m"
SL_PCT = 0.004
TP_PCT = 0.008
VOL_MIN = 1.15
VOL_MAX = 1.65
MAX_DIST_EMA = 0.01

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def check_signal():
    df = yf.download(SYMBOL, period="5d", interval=TIMEFRAME, progress=False)
    df = df.dropna()
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    if len(df) < 250: return

    df['EMA200'] = ta.trend.ema_indicator(df['Close'], window=200)
    df['EMA9'] = ta.trend.ema_indicator(df['Close'], window=9)
    df['EMA20'] = ta.trend.ema_indicator(df['Close'], window=20)
    df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
    df['RSI_DELTA'] = df['RSI'].diff()
    macd = ta.trend.MACD(df['Close'])
    df['MACD'] = macd.macd()
    df['MACD_SIG'] = macd.macd_signal()
    df['VOL_AVG'] = df['Volume'].rolling(20).mean()
    df['VOL_RATIO'] = df['Volume'] / df['VOL_AVG']

    last = df.iloc[-1]
    prev = df.iloc[-2]
    close = float(last['Close'])
    ema200 = float(last['EMA200'])
    ema9 = float(last['EMA9'])
    ema20 = float(last['EMA20'])
    rsi = float(last['RSI'])
    rsi_delta = float(last['RSI_DELTA'])
    macd_line = float(last['MACD'])
    macd_sig = float(last['MACD_SIG'])
    vol_ratio = float(last['VOL_RATIO'])

    dist_ema = abs(close - ema200) / ema200
    ema_filter = dist_ema <= MAX_DIST_EMA
    vol_filter = VOL_MIN <= vol_ratio <= VOL_MAX
    cross_up = prev['EMA9'] < prev['EMA20'] and last['EMA9'] > last['EMA20']
    cross_down = prev['EMA9'] > prev['EMA20'] and last['EMA9'] < last['EMA20']

    long_cond = close > ema200 and ema_filter and cross_up and (35 < rsi < 68 and rsi_delta > 4) and (macd_line > macd_sig) and vol_filter
    short_cond = close < ema200 and ema_filter and cross_down and (32 < rsi < 65 and rsi_delta < -4) and (macd_line < macd_sig) and vol_filter

    print(f"[{datetime.now()}] {close:.2f} RSI:{rsi:.1f} Vol:{vol_ratio:.2f}x")

    if long_cond:
        sl = close * (1 - SL_PCT); tp = close * (1 + TP_PCT)
        send_telegram(f"🔼 LONG XAU V3 📈\nPrice: {close:.2f}\nTP: {tp:.2f} (+0.8%)\nSL: {sl:.2f} (-0.4%)\nRR 1:2")

    if short_cond:
        sl = close * (1 + SL_PCT); tp = close * (1 - TP_PCT)
        send_telegram(f"🔻 SHORT XAU V3 📉\nPrice: {close:.2f}\nTP: {tp:.2f} (-0.8%)\nSL: {sl:.2f} (+0.4%)\nRR 1:2")

print("Bot started...")
send_telegram("✅ XAU V3 Bot is LIVE on Render!")

while True:
    try:
        check_signal()
    except Exception as e:
        print(f"Error: {e}")
    time.sleep(60)
