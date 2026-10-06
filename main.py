import os, requests, time, threading
from flask import Flask

TOKEN=os.getenv("TELEGRAM_TOKEN")
CHAT=os.getenv("CHAT_ID")
app=Flask(__name__)

def boot():
    time.sleep(5)
    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook")
        r=requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data={"chat_id":CHAT,"text":"✅ FINAL TEST - Bot is now working on Render!"})
        print(r.text)
    except Exception as e:
        print(e)

threading.Thread(target=boot, daemon=True).start()

@app.route("/")
def h(): return "LIVE"

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
