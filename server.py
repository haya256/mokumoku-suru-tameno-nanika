import base64
import binascii
import hmac
import mimetypes
import os
import random
import re
import secrets
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import json as _json
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify, send_from_directory, Response
from datetime import datetime

# サーバーのOSタイムゾーン(EC2は既定でUTC)に関わらず、入退室記録をJST(クライアント側の時刻)と揃える
os.environ["TZ"] = "Asia/Tokyo"
time.tzset()

# Python標準のmimetypesは.webpを認識しない(3.12時点)ため、Content-Typeが正しく付くよう明示登録する。
# 未登録のままだとブラウザがimgタグで表示できない形で配信されてしまう
mimetypes.add_type("image/webp", ".webp")

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
ROOM_IMAGE_PATTERN = re.compile(r"^room-image-\d+\.webp$")
_settings_write_lock = threading.Lock()

# ワールドマップ: 他のもくもくルーム(ピア)の情報を自分のサーバーが取りに行って参加者に中継する。
# ブラウザから相手サーバーを直接叩かせないことで、CORS設定が不要になり、参加者が何人いても
# 相手への負荷が一定になり、参加者のIPが相手に渡らない
MAX_PEERS = 8            # 中央(自分)を除いた3×3マップの周囲8マス
PEER_POLL_INTERVAL = 5   # ピアを巡回する間隔(秒)。クライアントの2秒pollとは独立
PEER_TIMEOUT = 5
PEER_JSON_MAX = 1_000_000
PEER_IMAGE_MAX = 2_000_000
PEER_IMAGE_MAX_AGE = 300 # 部屋画像を取り直すまでの最長時間(秒)
WEBP_MAGIC_HEAD = b"RIFF"
WEBP_MAGIC_TAIL = b"WEBP"
peer_cache = {}         # peer_id -> {"board": [...], "messages": [...], "roomImageVersion": int, "ok": bool}
peer_images = {}        # peer_id -> {"data": bytes, "version": int|None, "at": float}
peer_chara_images = {}  # (peer_id, cid) -> {"data": bytes, "version": str}

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

# 読み→変更→書きをロックの内側でまとめて行う。mutateは settings dict を直接書き換える関数で、
# その戻り値をそのまま呼び出し元に返す(追加したピアなど、書き込み結果を知りたい場合のため)
def update_settings(mutate):
    with _settings_write_lock:
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                settings = _json.load(f)
        except (OSError, ValueError):
            settings = {}
        result = mutate(settings)
        save_settings(settings)
        return result

# appearance.room_imageだけを部分更新する。filenameはlist_room_images()で検証済みの前提
def set_room_image_setting(filename):
    def mutate(settings):
        settings.setdefault("appearance", {})["room_image"] = f"{ROOM_IMAGE_DIR}/{filename}"
    update_settings(mutate)

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

# ピア一覧は毎回settings.jsonから読み直す。巡回スレッドもこれを使うので、管理者はサーバー稼働中に
# 接続・解除でき再起動が要らない(合言葉や部屋画像が再起動不要なのと同じ流儀)
def load_peers():
    peers = load_settings().get("world", {}).get("peers")
    return [p for p in peers if isinstance(p, dict)] if isinstance(peers, list) else []

def find_peer(peer_id):
    return next((p for p in load_peers() if p.get("id") == peer_id), None)

# 受け付けるのはホストまでのURLだけ。パス付きは中継先URLの組み立てが壊れるので弾く。
# schemeを絞るのは、取得した中身を参加者に中継する以上file:などを踏ませないため
def normalize_peer_url(url):
    url = (url or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    if parsed.path or parsed.query or parsed.fragment:
        return None
    return url

def add_peer(url, name):
    def mutate(settings):
        world = settings.setdefault("world", {})
        peers = [p for p in world.get("peers", []) if isinstance(p, dict)]
        world["peers"] = peers
        if any(p.get("url") == url for p in peers):
            return {"error": "duplicate"}
        if len(peers) >= MAX_PEERS:
            return {"error": "full"}
        # 空いているマスからランダムに選んで以降固定。設定に保存するので再起動しても動かない
        used = {p.get("slot") for p in peers}
        peer = {"id": secrets.token_hex(4), "url": url, "name": name,
                "slot": random.choice([s for s in range(MAX_PEERS) if s not in used])}
        peers.append(peer)
        return {"peer": peer}
    return update_settings(mutate)

def remove_peer(peer_id):
    def mutate(settings):
        world = settings.setdefault("world", {})
        peers = [p for p in world.get("peers", []) if isinstance(p, dict)]
        world["peers"] = [p for p in peers if p.get("id") != peer_id]
        return next((p for p in peers if p.get("id") == peer_id), None)
    return update_settings(mutate)

# 中継先は下記の決め打ちパスのみ。任意パスのプロキシにはしない
def fetch_peer_bytes(url, limit):
    req = urllib.request.Request(url, headers={"User-Agent": "mokumoku-bot/1.0"})
    with urllib.request.urlopen(req, timeout=PEER_TIMEOUT) as res:
        data = res.read(limit + 1)
    if len(data) > limit:
        raise ValueError("response too large")
    return data

def fetch_peer_json(url):
    return _json.loads(fetch_peer_bytes(url, PEER_JSON_MAX).decode("utf-8"))

# 失敗してもboard/messagesは前回値を残してok=Falseにするだけ。一瞬の通信断で
# 相手の部屋から人が消えたように見えるのを避ける(クライアント側はグレーアウト表示にする)
def refresh_peer(peer):
    pid, url = peer["id"], peer["url"]
    try:
        board = fetch_peer_json(f"{url}/board")
        msgs = fetch_peer_json(f"{url}/messages")
        status = fetch_peer_json(f"{url}/status")
        if not isinstance(board, list) or not isinstance(msgs, list) or not isinstance(status, dict):
            raise ValueError("unexpected payload")
        version = status.get("roomImageVersion")
        peer_cache[pid] = {"board": board, "messages": msgs,
                           "roomImageVersion": version if isinstance(version, int) else 0, "ok": True}
    except Exception as e:
        peer_cache[pid] = {**peer_cache.get(pid, {}), "ok": False}
        print(f"[peers] {peer.get('name') or url}: {e}")
        return
    # 画像の取得失敗でピア全体をオフライン扱いにはしない(在室者やチャットは取れているため)
    try:
        refresh_peer_image(pid, url, version)
    except Exception as e:
        print(f"[peers] {peer.get('name') or url} の部屋画像: {e}")

# 部屋画像は相手のバージョンが変わったときだけ取り直す(毎回取ると数百KBが5秒おきに流れる)。
# ただし相手が再起動するとバージョンは0に戻るので、それだけに頼らず一定時間で取り直す
def refresh_peer_image(pid, url, version):
    cached = peer_images.get(pid)
    if cached and cached["version"] == version and time.time() - cached["at"] < PEER_IMAGE_MAX_AGE:
        return
    data = fetch_peer_bytes(f"{url}/room-image.webp", PEER_IMAGE_MAX)
    # 中継するバイト列が本当に画像かは相手任せにせずこちらでも確かめる
    if data[:4] != WEBP_MAGIC_HEAD or data[8:12] != WEBP_MAGIC_TAIL:
        raise ValueError("not a webp image")
    peer_images[pid] = {"data": data, "version": version, "at": time.time()}

def poll_peers_once():
    peers = load_peers()
    ids = {p.get("id") for p in peers}
    # 設定から消えたピアのキャッシュは捨てる。残すとメモリを食い続けるうえ、
    # 同じURLを付け直したときに取り直す前の古い内容が一瞬見えてしまう
    for pid in [p for p in peer_cache if p not in ids]:
        peer_cache.pop(pid, None)
        peer_images.pop(pid, None)
    for key in [k for k in peer_chara_images if k[0] not in ids]:
        peer_chara_images.pop(key, None)
    targets = [p for p in peers if p.get("id") and p.get("url")]
    if targets:
        # 応答しないピアが他のピアの鮮度を巻き添えにしないよう並列に取りに行く
        with ThreadPoolExecutor(max_workers=MAX_PEERS) as pool:
            list(pool.map(refresh_peer, targets))

def peer_poll_loop():
    while True:
        try:
            poll_peers_once()
        except Exception as e:
            print(f"[peers] loop error: {e}")
        time.sleep(PEER_POLL_INTERVAL)

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

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

# 部屋の画像は config/settings.json の appearance.room_image で差し替え可能(再起動不要)
@app.route("/room-image.webp")
def room_image():
    path = load_settings().get("appearance", {}).get("room_image") or "assets/room-image-1.webp"
    directory, filename = os.path.split(path)
    return send_from_directory(directory or ".", filename)

# 選択パネル用のプレビュー配信。list_room_images()に含まれるファイル名以外は404にする。
# 画像バイト自体は/room-image.webpと同様に非機密の装飾素材なので認証は課さない
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

# ピアの部屋画像を中継。実体は巡回スレッドが取得済みのバイト列なので、ここでは相手サーバーに触れない。
# /room-image-preview と同じくGETに合言葉は載せない方針
@app.route("/peer-room-image/<peer_id>.webp")
def peer_room_image(peer_id):
    img = peer_images.get(peer_id)
    if not img or not find_peer(peer_id):
        return jsonify({"error": "not found"}), 404
    return Response(img["data"], mimetype="image/webp",
                    headers={"X-Content-Type-Options": "nosniff",
                             "Cache-Control": "public, max-age=86400"})

# ピア参加者のカスタムキャラ画像を中継。人数分あって大半は使われないので巡回時には先読みせず、
# 要求された時点で取りに行って (peer_id, cid) 単位でキャッシュする
@app.route("/peer-chara/<peer_id>/<cid>.png")
def peer_chara(peer_id, cid):
    peer = find_peer(peer_id)
    if not peer:
        return jsonify({"error": "not found"}), 404
    version = request.args.get("v", "")
    cached = peer_chara_images.get((peer_id, cid))
    if not cached or cached["version"] != version:
        try:
            data = fetch_peer_bytes(
                f"{peer['url']}/chara-custom/{urllib.parse.quote(cid, safe='')}.png", PEER_IMAGE_MAX)
        except Exception:
            return jsonify({"error": "unavailable"}), 502
        # 中継するバイト列が本当に画像かは相手任せにせずこちらでも確かめる
        if not data.startswith(PNG_MAGIC):
            return jsonify({"error": "unavailable"}), 502
        cached = {"data": data, "version": version}
        peer_chara_images[(peer_id, cid)] = cached
    return Response(cached["data"], mimetype="image/png",
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

# 巡回スレッドが貯めたピアの状態をまとめて返す。ここから相手サーバーへのアクセスは発生しないので、
# クライアントの2秒pollと相手を叩く5秒間隔は完全に独立している
@app.route("/world")
def get_world():
    peers = []
    for peer in load_peers():
        cached = peer_cache.get(peer.get("id"), {})
        peers.append({
            "id": peer.get("id"),
            "name": peer.get("name") or urllib.parse.urlparse(peer.get("url", "")).netloc,
            "slot": peer.get("slot", 0),
            # 未取得はnull(「接続中」表示)、Falseは「接続できません」表示
            "ok": cached.get("ok"),
            # 部屋画像が中継できる状態か。取得前にクライアントが404を踏むのを避けるために返す
            "hasImage": peer.get("id") in peer_images,
            "board": cached.get("board", []),
            "messages": cached.get("messages", []),
            "roomImageVersion": cached.get("roomImageVersion", 0),
        })
    return jsonify({"peers": peers})

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
        "ts": time.time(),
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
    current_path = load_settings().get("appearance", {}).get("room_image") or f"{ROOM_IMAGE_DIR}/room-image-1.webp"
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

# ピア一覧の取得: 管理者合言葉必須(kick/room-imagesと同型のゲート)
@app.route("/admin/peers", methods=["POST"])
def admin_peers():
    data = request.get_json()
    supplied = ((data or {}).get("passphrase") or "").strip()
    if not is_admin_passphrase(supplied):
        return jsonify({"error": "admin required"}), 403
    peers = [{"id": p.get("id"), "url": p.get("url"), "name": p.get("name")} for p in load_peers()]
    return jsonify({"peers": peers, "max": MAX_PEERS})

# 接続・解除の実行: 一覧取得の成否とは別に、実行時も毎回サーバー側で合言葉を検証する
@app.route("/admin/peer", methods=["POST"])
def admin_peer():
    data = request.get_json() or {}
    supplied = (data.get("passphrase") or "").strip()
    if not is_admin_passphrase(supplied):
        return jsonify({"error": "admin required"}), 403
    action = (data.get("action") or "").strip()
    if action == "add":
        url = normalize_peer_url(data.get("url"))
        if not url:
            return jsonify({"error": "invalid url"}), 400
        # 名前はシステムメッセージとDiscordにも載るので、改行を潰して長さを切る
        name = " ".join((data.get("name") or "").split())[:40] or urllib.parse.urlparse(url).netloc
        result = add_peer(url, name)
        if result.get("error") == "duplicate":
            return jsonify({"error": "already connected"}), 400
        if result.get("error") == "full":
            return jsonify({"error": "peer limit reached"}), 400
        add_system_message(f"🌏 管理者が「{name}」とつながりました")
        return jsonify({"ok": True, "peer": result["peer"]})
    if action == "remove":
        removed = remove_peer((data.get("id") or "").strip())
        if removed:
            add_system_message(f"🌏 管理者が「{removed.get('name')}」との接続を解除しました")
        return jsonify({"ok": True})
    return jsonify({"error": "invalid action"}), 400

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

# waitress以外から起動された場合も巡回が回るよう、__main__ではなくモジュール読み込み時に開始する
threading.Thread(target=peer_poll_loop, daemon=True).start()

if __name__ == "__main__":
    from waitress import serve
    port = int(os.environ.get("PORT", "5000"))
    print(f"もくもくサーバー起動: http://127.0.0.1:{port} (停止は Ctrl+C)", flush=True)
    serve(app, host="127.0.0.1", port=port)
