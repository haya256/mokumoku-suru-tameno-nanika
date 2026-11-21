import json as _json
import os
import secrets
import time
import urllib.request
from datetime import datetime

from mokumoku import net
from mokumoku.media import sniff_image_mime
from mokumoku.state import messages

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
DISCORD_CONTENT_MAX = 2000
# 直近のDiscord送信結果。None=未送信。URL失効(404)等に画面で気づけるように保持する
discord_last_ok = None

# Discord連携の現在状態: off=URL未設定 / on=設定済み / error=直近の送信が失敗(URL失効など)
def discord_status():
    if not DISCORD_WEBHOOK_URL:
        return "off"
    return "error" if discord_last_ok is False else "on"

# Discordへ送る添付ファイルの名前。チャット画像はWebP/JPEGのどちらか(media.CHAT_IMAGE_MIMES)
IMAGE_FILENAMES = {"image/webp": "image.webp", "image/jpeg": "image.jpg", "image/png": "image.png"}

# 画像つきの投稿はmultipart/form-dataで送る(本文はpayload_json、画像はfiles[0])
def _multipart(payload, image):
    mime = sniff_image_mime(image) or "application/octet-stream"
    filename = IMAGE_FILENAMES.get(mime, "image")
    boundary = secrets.token_hex(16)
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="payload_json"\r\n',
        b"Content-Type: application/json\r\n\r\n",
        payload, b"\r\n",
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="files[0]"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        image, b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return body, f"multipart/form-data; boundary={boundary}"

# imageはチャットに貼られた画像のバイト列(任意)。渡されたら添付ファイルとして一緒に送る
def post_to_discord(content, image=None):
    global discord_last_ok
    if not DISCORD_WEBHOOK_URL:
        return
    # Discordは2000文字を超える投稿を断るので、収まるように切る
    payload = _json.dumps({"content": content[:DISCORD_CONTENT_MAX]}).encode()
    if image:
        data, content_type = _multipart(payload, image)
    else:
        data, content_type = payload, "application/json"
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL,
        data=data,
        headers={"Content-Type": content_type, "User-Agent": net.USER_AGENT},
        method="POST",
    )
    # 画像を送るときは送信に時間がかかるので、待ち時間を長めにとる
    timeout = net.TIMEOUT * 3 if image else net.TIMEOUT
    try:
        urllib.request.urlopen(req, timeout=timeout)
        discord_last_ok = True
    except Exception as e:
        discord_last_ok = False
        print(f"[Discord] error: {e}")

# tsは自分のチャットとピアのチャットを1本の時系列にマージするための並び替えキー。
# 表示は従来どおりtimeを使う。idはワールド接続プロトコルで発言を識別するため(spec §5)
def add_system_message(text):
    messages.append({
        "id": secrets.token_urlsafe(8),
        "name": "",
        "text": text,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ts": time.time(),
        "system": True,
    })
    post_to_discord(text)
