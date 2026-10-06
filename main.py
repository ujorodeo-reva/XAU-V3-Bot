import os, requests, threading, time
from flask import Flask

TOKEN = os.getenv("TELEGRAM_TOKEN","").strip()
CHAT = os.getenv("CHAT_ID","").strip()
print(f"START TOKEN {TOKEN[:8]} CHAT {CHAT}", flush=True)

app = Flask(__name__)

def boot():
    time.sleep(3)
    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook", timeout=10)
        r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data={"chat_id":CHAT,"text":"✅ RENDER IS WORKING NOW - V8.7"}, timeout=10)
        print(f"SEND RESULT {r.text}", flush=True)
    except Exception as e:
        print(f"ERROR {e}", flush=True)

threading.Thread(target=boot, daemon=True).start()

@app.route("/")
def h(): return "OK"

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
