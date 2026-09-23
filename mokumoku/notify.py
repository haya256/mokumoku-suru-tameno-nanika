import json as _json
import os
import time
import urllib.request
from datetime import datetime

from mokumoku.state import messages

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
# 直近のDiscord送信結果。None=未送信。URL失効(404)等に画面で気づけるように保持する
discord_last_ok = None

# Discord連携の現在状態: off=URL未設定 / on=設定済み / error=直近の送信が失敗(URL失効など)
def discord_status():
    if not DISCORD_WEBHOOK_URL:
        return "off"
    return "error" if discord_last_ok is False else "on"

def post_to_discord(content):
    global discord_last_ok
    if not DISCORD_WEBHOOK_URL:
        return
    payload = _json.dumps({"content": content}).encode()
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "mokumoku-bot/1.0"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5)
        discord_last_ok = True
    except Exception as e:
        discord_last_ok = False
        print(f"[Discord] error: {e}")

# tsは自分のチャットとピアのチャットを1本の時系列にマージするための並び替えキー。
# 表示は従来どおりtimeを使う
def add_system_message(text):
    messages.append({
        "name": "",
        "text": text,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ts": time.time(),
        "system": True,
    })
    post_to_discord(text)
