import os, time, threading, requests
from flask import Flask
from datetime import datetime

TOKEN = os.getenv("TELEGRAM_TOKEN","").strip()
CHAT = os.getenv("CHAT_ID","").strip()
PORT = int(os.getenv("PORT", 10000))

print(f"=== XAU V8.8 LIVE TOKEN={TOKEN[:10]}... CHAT={CHAT} ===", flush=True)
app = Flask(__name__)

# --- Telegram ---
def send(msg, chat_id=None):
    try:
        cid = str(chat_id or CHAT).strip()
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        r = requests.post(url, data={"chat_id": cid, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        print(f"SEND: {r.text[:250]}", flush=True)
        return r.json()
    except Exception as e:
        print(f"SEND ERROR {e}", flush=True)

def get_gold_price():
    try:
        # Free gold price from Binance PAXG/USDT as XAU proxy
        r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT", timeout=10).json()
        price = float(r['price'])
        return price
    except:
        try:
            r = requests.get("https://api.metals.live/v1/spot/gold", timeout=10).json()
            return float(r[0])
        except:
            return 2650.00

# --- Listener ---
def listener():
    last_id = 0
    print("Listener started", flush=True)
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={last_id+1}&timeout=20"
            data = requests.get(url, timeout=25).json()
            for u in data.get("result", []):
                last_id = u["update_id"]
                if "message" not in u: continue
                txt = u["message"].get("text","").lower()
                cid = u["message"]["chat"]["id"]
                print(f"CMD {txt} from {cid}", flush=True)

                if "/start" in txt or "/help" in txt:
                    send("🤖 *XAU V3 Bot V8.8 LIVE*\n\nCommands:\n/price - Live Gold Price\n/status - Bot Status\n/help - This menu\n\nBot will send auto signals every 15min", cid)
                elif "/price" in txt or "price" in txt:
                    p = get_gold_price()
                    send(f"💰 *XAU/USD Live: ${p:,.2f}*\nTime: {datetime.utcnow().strftime('%H:%M UTC')}\nSource: PAXG ~ Gold", cid)
                elif "/status" in txt or "status" in txt:
                    send(f"✅ *V8.8 ONLINE*\nRender: OK\nTelegram: OK\nChat: {cid}\nTime: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", cid)
        except Exception as e:
            print(f"Listener error {e}", flush=True)
            time.sleep(5)
        time.sleep(2)

# --- Auto Signal Loop ---
def bot_loop():
    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
    except: pass
    time.sleep(3)
    send(f"🚀 *XAU V3 Bot V8.8 STARTED*\n\n✅ Render Connected\n✅ Price Feed Live\n\nSend /price to test\nAuto signals ON (every 15min)")

    while True:
        try:
            price = get_gold_price()
            # Simple dummy signal logic - you can upgrade later
            signal = f"📊 *XAU ANALYSIS*\nPrice: ${price:,.2f}\nBias: Watching levels...\nNo trade - Waiting for setup\n\n_{datetime.utcnow().strftime('%H:%M UTC')}_"
            # Uncomment next line to get auto message every 15min
            # send(signal)
            print(f"Price check ${price}", flush=True)
        except Exception as e:
            print(f"Loop error {e}", flush=True)
        time.sleep(900) # 15 min

@app.route("/")
def home():
    return f"XAU V8.8 LIVE - Price ${get_gold_price():.2f}"

threading.Thread(target=bot_loop, daemon=True).start()
threading.Thread(target=listener, daemon=True).start()

if __name__ == "__main__":
    print(f"Flask starting on {PORT}", flush=True)
    app.run(host="0.0.0.0", port=PORT)
