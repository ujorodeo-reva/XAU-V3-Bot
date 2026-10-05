import os, time, threading, requests
from flask import Flask

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

app = Flask(__name__)

def send_tg(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
        print(f"SENT: {text[:50]}")
    except Exception as e:
        print(f"SEND FAIL: {e}")

def telegram_loop():
    print("=== BOT POLLING STARTED ===")
    print(f"Listening for chat_id={CHAT_ID}")
    offset = 0
    while True:
        try:
            r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                             params={"offset": offset, "timeout": 20}, timeout=25).json()
            for upd in r.get("result", []):
                offset = upd["update_id"]+1
                msg = upd.get("message",{})
                text = msg.get("text","")
                from_id = str(msg.get("from",{}).get("id",""))
                chat = str(msg.get("chat",{}).get("id",""))
                print(f"INCOMING: from={from_id} chat={chat} text={text}")
                if chat != CHAT_ID and from_id != CHAT_ID:
                    print(f"IGNORED - not authorized. Your CHAT_ID should be {chat} or {from_id}")
                    send_tg(f"Your chat ID is: {chat}\nUpdate it in Render!")
                    continue
                if "/status" in text or "/start" in text:
                    send_tg("✅ Bot is ONLINE\nXAU V3.0 Running\nSend /status anytime")
                else:
                    send_tg(f"Got: {text}\nBot is alive")
        except Exception as e:
            print(f"POLL ERROR: {e}")
            time.sleep(3)

@app.route("/")
def home():
    return "XAU Bot Running - V8.3"

if __name__ != "__main__":
    # When run by gunicorn, start thread
    threading.Thread(target=telegram_loop, daemon=True).start()

if __name__ == "__main__":
    threading.Thread(target=telegram_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
