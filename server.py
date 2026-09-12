import base64
import binascii
import hmac
import os
import random
import re
import tempfile
import threading
import time
import urllib.request
import json as _json
from flask import Flask, request, jsonify, send_from_directory, Response
from datetime import datetime

# サーバーのOSタイムゾーン(EC2は既定でUTC)に関わらず、入退室記録をJST(クライアント側の時刻)と揃える
os.environ["TZ"] = "Asia/Tokyo"
time.tzset()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
messages = []
board = {}
# カスタムキャラ画像は board と同じライフサイクル(退室で破棄、再起動で消える)
custom_images = {}  # cid -> {"data": bytes, "v": int}
_img_seq = 0  # キャッシュバスター用の通し番号。退室しても巻き戻さない(再入室時のキャッシュ誤爆防止)
room_image_version = 0  # 部屋画像が変更されるたびに+1(クライアントが変化検知するためだけの値)
MAX_IMAGE_B64 = 700_000
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ROOM_COUNT = 9
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
# 直近のDiscord送信結果。None=未送信。URL失効(404)等に画面で気づけるように保持する
discord_last_ok = None
SETTINGS_FILE = "config/settings.json"
DEFAULT_PASSPHRASE_FILE = "config/合言葉.txt"
DEFAULT_ADMIN_PASSPHRASE_FILE = "config/管理者合言葉.txt"
ROOM_IMAGE_DIR = "assets"
ROOM_IMAGE_PATTERN = re.compile(r"^room-image-\d+\.png$")
_settings_write_lock = threading.Lock()

# 設定は毎回読む(サーバー再起動なしでモード切替できるようにするため)
def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return _json.load(f)
    except (OSError, ValueError) as e:
        print(f"[settings] {SETTINGS_FILE} を読めないためデフォルト(mode=very_easy)で動作: {e}")
        return {}

# settings.jsonへの書き込みは他キー(security/deploy等)を保持したまま部分更新する。
# tmpファイル+os.replaceでアトミックに置換し、書き込み途中でプロセスが落ちても壊れたJSONを残さない
def save_settings(settings):
    directory = os.path.dirname(SETTINGS_FILE) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".settings-", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            _json.dump(settings, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, SETTINGS_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

# appearance.room_imageだけを部分更新する。filenameはlist_room_images()で検証済みの前提
def set_room_image_setting(filename):
    with _settings_write_lock:
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                settings = _json.load(f)
        except (OSError, ValueError):
            settings = {}
        settings.setdefault("appearance", {})["room_image"] = f"{ROOM_IMAGE_DIR}/{filename}"
        save_settings(settings)

# ファイルの中身を返す。未設置/空ならNone(hmac.compare_digestに渡す前提なので空文字とは区別する)
def read_secret_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            value = f.read().strip()
    except OSError:
        return None
    return value or None

def is_admin_passphrase(supplied):
    security = load_settings().get("security", {})
    path = security.get("admin_passphrase_file", DEFAULT_ADMIN_PASSPHRASE_FILE)
    expected = read_secret_file(path)
    if expected is None:
        return False
    return hmac.compare_digest((supplied or "").strip().encode(), expected.encode())

# 部屋画像として選択可能なファイルの一覧。命名規則を正規表現で完全一致させることで、
# 以降の処理はこの戻り値に含まれるかどうかだけで判定でき、パストラバーサルの余地がない
def list_room_images():
    try:
        names = os.listdir(ROOM_IMAGE_DIR)
    except OSError:
        return []
    return sorted(n for n in names if ROOM_IMAGE_PATTERN.fullmatch(n))

# セキュリティモード(デフォルト: very_easy):
#   none      … 認証なし(閲覧・書き込みとも自由)
#   very_easy … 閲覧は自由。書き込み系(投稿/入室/退室)は部屋共通の合言葉が必要。
#               ただし合言葉ファイルが未設置(または空)の間は認証なしで通す
# 管理者合言葉(config/管理者合言葉.txt)を入力した場合も、部屋共通の合言葉の代わりとして通す。
# これにより「合言葉欄に管理者合言葉を入れる」だけで通常の書き込み権限+管理者権限を両方得られる。
def check_passphrase(data):
    security = load_settings().get("security", {})
    if security.get("mode", "very_easy") != "very_easy":
        return None
    path = security.get("passphrase_file", DEFAULT_PASSPHRASE_FILE)
    expected = read_secret_file(path)
    if expected is None:
        return None
    supplied = ((data or {}).get("passphrase") or "").strip()
    if hmac.compare_digest(supplied.encode(), expected.encode()):
        return None
    if is_admin_passphrase(supplied):
        return None
    return jsonify({"error": "wrong passphrase", "authRequired": True}), 401

# クライアントがcanvasで縮小・PNG化したデータURLを検証してPNGバイト列を返す。不正ならNone
def decode_chara_image(image):
    prefix = "data:image/png;base64,"
    if not isinstance(image, str) or not image.startswith(prefix) or len(image) > MAX_IMAGE_B64:
        return None
    try:
        raw = base64.b64decode(image[len(prefix):], validate=True)
    except (ValueError, binascii.Error):
        return None
    if not raw.startswith(PNG_MAGIC):
        return None
    return raw

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

def add_system_message(text):
    messages.append({
        "name": "",
        "text": text,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "system": True,
    })
    post_to_discord(text)

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

# 部屋の画像は config/settings.json の appearance.room_image で差し替え可能(再起動不要)
@app.route("/room-image.png")
def room_image():
    path = load_settings().get("appearance", {}).get("room_image") or "assets/room-image-1.png"
    directory, filename = os.path.split(path)
    return send_from_directory(directory or ".", filename)

# 選択パネル用のプレビュー配信。list_room_images()に含まれるファイル名以外は404にする。
# 画像バイト自体は/room-image.pngと同様に非機密の装飾素材なので認証は課さない
# (GETのURL/クエリに合言葉を乗せる設計はログ等に残るリスクがあり、既存のPOST body方式に反するため)
@app.route("/room-image-preview/<name>")
def room_image_preview(name):
    if name not in list_room_images():
        return jsonify({"error": "not found"}), 404
    return send_from_directory(ROOM_IMAGE_DIR, name)

@app.route("/chara-image.png")
def chara_image():
    return send_from_directory("assets", "chara-image-1.png")

# インメモリdictの参照のみ(ファイルシステム非接触)。バージョン付きURLで配信するので長めにキャッシュ可
@app.route("/chara-custom/<cid>.png")
def chara_custom(cid):
    img = custom_images.get(cid)
    if not img:
        return jsonify({"error": "not found"}), 404
    return Response(img["data"], mimetype="image/png",
                    headers={"X-Content-Type-Options": "nosniff",
                             "Cache-Control": "public, max-age=86400"})

# Discord連携の現在状態: off=URL未設定 / on=設定済み / error=直近の送信が失敗(URL失効など)
@app.route("/status")
def get_status():
    if not DISCORD_WEBHOOK_URL:
        discord = "off"
    elif discord_last_ok is False:
        discord = "error"
    else:
        discord = "on"
    return jsonify({"discord": discord, "roomImageVersion": room_image_version})

@app.route("/messages", methods=["GET"])
def get_messages():
    return jsonify(messages)

@app.route("/messages", methods=["POST"])
def post_message():
    data = request.get_json()
    err = check_passphrase(data)
    if err:
        return err
    name = data.get("name", "").strip()
    text = data.get("text", "").strip()
    if not name or not text:
        return jsonify({"error": "name and text required"}), 400
    msg = {
        "name": name,
        "text": text,
        "time": datetime.now().strftime("%H:%M"),
    }
    messages.append(msg)
    post_to_discord(f"**{name}**: {text}")
    return jsonify(msg), 201

@app.route("/board", methods=["GET"])
def get_board():
    return jsonify(list(board.values()))

# board はクライアントID(ブラウザごとに固定)をキーに持つ。名前は表示用で変更可
@app.route("/board/join", methods=["POST"])
def join_board():
    data = request.get_json()
    err = check_passphrase(data)
    if err:
        return err
    cid = (data.get("id") or "").strip()
    name = (data.get("name") or "").strip()
    task = (data.get("task") or "").strip()
    if not cid or not name or not task:
        return jsonify({"error": "id, name and task required"}), 400
    start = (data.get("start") or "").strip() or datetime.now().strftime("%H:%M")
    end = (data.get("end") or "").strip()
    is_new = cid not in board
    if is_new:
        used = {e["room"] for e in board.values()}
        free = [r for r in range(1, ROOM_COUNT + 1) if r not in used]
        if not free:
            return jsonify({"roomFull": True}), 200
        room = random.choice(free)
        pose = random.randint(0, 2)
    else:
        room = board[cid]["room"]
        pose = board[cid]["pose"]
        old_name = board[cid]["name"]
        if old_name != name:
            add_system_message(f"✏️ {old_name} が {name} に名前を変更")
    # 画像は任意。未送信なら既存のカスタム画像を維持(imgvはcustom_imagesから再計算)
    image = data.get("image")
    if image:
        raw = decode_chara_image(image)
        if raw is None:
            return jsonify({"error": "invalid image"}), 400
        global _img_seq
        _img_seq += 1
        custom_images[cid] = {"data": raw, "v": _img_seq}
    imgv = custom_images.get(cid, {}).get("v", 0)
    board[cid] = {"id": cid, "name": name, "start": start, "end": end, "task": task, "room": room, "pose": pose, "imgv": imgv}
    if is_new:
        until = f"〜{end}" if end else "〜"
        add_system_message(f"🟢 {name} がルーム{room}に入室してもくもく開始({start}{until}): {task}")
    return jsonify(board[cid]), 201

# クライアントが今保持している合言葉が管理者合言葉と一致するか確認するだけの読み取り専用エンドポイント。
# 一致すればクライアント側で「強制退出」ボタンを表示する(実際の実行権限はkick側でも都度検証する)
@app.route("/admin/status", methods=["POST"])
def admin_status():
    data = request.get_json()
    supplied = ((data or {}).get("passphrase") or "").strip()
    return jsonify({"isAdmin": is_admin_passphrase(supplied)})

@app.route("/board/kick", methods=["POST"])
def kick_board():
    data = request.get_json()
    supplied = ((data or {}).get("passphrase") or "").strip()
    if not is_admin_passphrase(supplied):
        return jsonify({"error": "admin required"}), 403
    cid = (data.get("id") or "").strip()
    entry = board.pop(cid, None)
    custom_images.pop(cid, None)
    if entry:
        add_system_message(f"🚫 {entry['name']} が管理者によりルーム{entry['room']}から強制退室させられました")
    return jsonify({"ok": True})

# 画像一覧取得: 管理者合言葉必須(kickと同型のゲート)。画像バイト自体はroom_image_previewで別途取得させる
@app.route("/admin/room-images", methods=["POST"])
def admin_room_images():
    data = request.get_json()
    supplied = ((data or {}).get("passphrase") or "").strip()
    if not is_admin_passphrase(supplied):
        return jsonify({"error": "admin required"}), 403
    current_path = load_settings().get("appearance", {}).get("room_image") or f"{ROOM_IMAGE_DIR}/room-image-1.png"
    return jsonify({"images": list_room_images(), "current": os.path.basename(current_path)})

# 画像変更の実行: 一覧取得の成否とは別に、実行時も毎回サーバー側で合言葉を検証する
@app.route("/admin/room-image", methods=["POST"])
def admin_set_room_image():
    global room_image_version
    data = request.get_json()
    supplied = ((data or {}).get("passphrase") or "").strip()
    if not is_admin_passphrase(supplied):
        return jsonify({"error": "admin required"}), 403
    filename = (data.get("file") or "").strip()
    if filename not in list_room_images():
        return jsonify({"error": "invalid file"}), 400
    set_room_image_setting(filename)
    room_image_version += 1
    add_system_message(f"🖼️ 管理者が部屋画像を {filename} に変更しました")
    return jsonify({"ok": True, "file": filename, "version": room_image_version})

@app.route("/board/leave", methods=["POST"])
def leave_board():
    data = request.get_json()
    err = check_passphrase(data)
    if err:
        return err
    cid = (data.get("id") or "").strip()
    entry = board.pop(cid, None)
    custom_images.pop(cid, None)  # 画像はその入室の間だけ有効
    if not entry:
        return jsonify({"ok": True})
    now = datetime.now()
    end_str = now.strftime("%H:%M")
    try:
        h, m = map(int, entry["start"].split(":"))
        minutes = (now.hour * 60 + now.minute - h * 60 - m) % (24 * 60)
    except ValueError:
        minutes = 0
    # 人間可読かつ機械処理しやすい固定順の1行記録
    record = f"{now.strftime('%Y-%m-%d')} | {entry['start']}〜{end_str} | {minutes}分 | {entry['task']}"
    add_system_message(f"🔴 {entry['name']} がルーム{entry['room']}から退室")
    return jsonify({"ok": True, "record": record})

if __name__ == "__main__":
    from waitress import serve
    print("もくもくサーバー起動: http://127.0.0.1:5000 (停止は Ctrl+C)", flush=True)
    serve(app, host="127.0.0.1", port=5000)
