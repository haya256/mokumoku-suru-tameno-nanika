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

import net
from kinds import AREA_KINDS, NPC_KINDS, KindError
from media import PNG_MAGIC, decode_chara_image, decode_chat_image, is_webp

# サーバーのOSタイムゾーン(EC2は既定でUTC)に関わらず、入退室記録をJST(クライアント側の時刻)と揃える
os.environ["TZ"] = "Asia/Tokyo"
time.tzset()

# Python標準のmimetypesは.webpを認識しない(3.12時点)ため、Content-Typeが正しく付くよう明示登録する。
# 未登録のままだとブラウザがimgタグで表示できない形で配信されてしまう
mimetypes.add_type("image/webp", ".webp")

app = Flask(__name__)
# チャット画像(WebP)をJSONボディに積むため、アバターのみだった頃の2MBから拡大
app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024
messages = []
board = {}
# カスタムキャラ画像は board と同じライフサイクル(退室で破棄、再起動で消える)
custom_images = {}  # cid -> {"data": bytes, "v": int}
npc_images = {}  # npc board id -> {"data": bytes, "mime": str, "version": str} (YouTube NPCのサムネ)
# チャットに添付された画像。messagesと同じく無制限に増え続け、再起動で消える(既存の割り切りに合わせる)
message_images = {}  # image id -> bytes
# 他サーバーのチャット画像を中継した際のキャッシュ。peer_chara_imagesと同じ役割
peer_message_images = {}  # (peer_id, image_id) -> bytes
_img_seq = 0  # キャッシュバスター用の通し番号。退室しても巻き戻さない(再入室時のキャッシュ誤爆防止)
room_image_version = 0  # 部屋画像が変更されるたびに+1(クライアントが変化検知するためだけの値)
# ルームの見た目状態(通常/準備中/Closed)。管理者専用の演出切り替え用
ROOM_STATES = ("normal", "preparing", "closed")
ROOM_STATE_LABELS = {"preparing": "準備中", "closed": "Closed"}  # システムメッセージ表示用
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
# 空き部屋の確保〜board書き込みまでの間に別リクエストが割り込むと部屋番号が重複しうる
# (waitressはデフォルトでマルチスレッド)。join_boardとNPC追加の両方でこの区間を守る
_board_lock = threading.Lock()

# ワールドマップ: 他のもくもくルーム(ピア)の情報を自分のサーバーが取りに行って参加者に中継する。
# ブラウザから相手サーバーを直接叩かせないことで、CORS設定が不要になり、参加者が何人いても
# 相手への負荷が一定になり、参加者のIPが相手に渡らない
MAX_AREAS = 8            # 中央(自分)を除いた3×3マップの周囲8マス
PEER_POLL_INTERVAL = 5   # ネイティブ型ピアを巡回する間隔(秒)。クライアントの2秒pollとは独立

# 実機のelm200 fork版で確認した部屋画像は1024x1024のPNGで約2.3MBあった(nativeのwebpより大きい)。
# それを弾かない程度の余裕を持たせつつ、無制限にはしない
PEER_IMAGE_MAX = 6_000_000
PEER_IMAGE_MAX_AGE = 300 # 部屋画像を取り直すまでの最長時間(秒)
# fork型ピア(FastAPI+Redisバックエンド、GET /api/events のSSEでスナップショット配信)のデフォルト巡回間隔。
# アクセス1回ごとに相手のRedisコマンドを複数消費するため、インメモリのネイティブ型より長めに取る。
# もくもく会は24時間稼働ではなく限られた時間だけ動かす運用が前提のため、1分程度なら実用上許容範囲。
# config/settings.json の world.fork_poll_interval_sec で管理者が調整できる(再起動不要)
FORK_POLL_INTERVAL_DEFAULT = 60
FORK_SSE_MAX = 2_000_000  # SSEの最初の1イベントを読む際の上限バイト数(以降は読まず切断する)

peer_cache = {}         # peer_id -> {"board": [...], "messages": [...], "roomImageVersion": int|str, "ok": bool}
area_images = {}        # area_id -> {"data": bytes, "mime": str, "version": int|str|None, "at": float}
peer_chara_images = {}  # (peer_id, cid) -> {"data": bytes, "version": str}
peer_last_polled = {}   # peer_id -> 最後に実際に取得を試みた時刻(fork型のみ使う)

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

# appearance.room_stateだけを部分更新する。stateはROOM_STATESで検証済みの前提
def set_room_state_setting(state):
    def mutate(settings):
        settings.setdefault("appearance", {})["room_state"] = state
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

# 管理者操作のログに載せる実行者名。クライアントが送る actorId(自分のクライアントID)から入室中の名前を引く。
# 見る専(未入室)などで名前が引けないときは「管理者」だけにする
def admin_label(data):
    entry = board.get(((data or {}).get("actorId") or "").strip())
    name = (entry or {}).get("name")
    return f"{name}（管理者）" if name else "管理者"

# 部屋画像として選択可能なファイルの一覧。命名規則を正規表現で完全一致させることで、
# 以降の処理はこの戻り値に含まれるかどうかだけで判定でき、パストラバーサルの余地がない
def list_room_images():
    try:
        names = os.listdir(ROOM_IMAGE_DIR)
    except OSError:
        return []
    return sorted(n for n in names if ROOM_IMAGE_PATTERN.fullmatch(n))

# エリア一覧は毎回settings.jsonから読み直す。巡回スレッドもこれを使うので、管理者はサーバー稼働中に
# 設置・撤去でき再起動が要らない(合言葉や部屋画像が再起動不要なのと同じ流儀)。
# 旧バージョンが書いたworld.peersは、kind未指定=peerとして読めるのでそのまま受け入れる
# (書き込み時にworld.areasへ正規化される)
def load_areas():
    world = load_settings().get("world", {})
    raw = world.get("areas")
    if not isinstance(raw, list):
        raw = world.get("peers")
    if not isinstance(raw, list):
        return []
    areas = []
    for a in raw:
        if not isinstance(a, dict):
            continue
        # kindは手書きされうる(settings.jsonは手編集可とREADMEで案内している)。
        # 欠損はpeer扱いにし、未知の種別は落とさずそのまま通す(クライアント側が霧マスにする)
        areas.append({**a, "kind": a.get("kind") or "peer"})
    return areas

def find_area(area_id):
    return next((a for a in load_areas() if a.get("id") == area_id), None)

# ピア(他のもくもくルーム)だけを抜き出す。巡回スレッドとチャット/在室者のマージはこちらを使う
def load_peers():
    return [a for a in load_areas() if a.get("kind") == "peer"]

def find_peer(peer_id):
    return next((p for p in load_peers() if p.get("id") == peer_id), None)

# fork型ピアの巡回間隔(秒)。settings.jsonのworld.fork_poll_interval_secで管理者が調整できる
# (再起動不要)。ネイティブ型より短くして相手に負担をかけないよう、下限をPEER_POLL_INTERVALに丸める
def fork_poll_interval():
    try:
        val = int(load_settings().get("world", {}).get("fork_poll_interval_sec", FORK_POLL_INTERVAL_DEFAULT))
    except (TypeError, ValueError):
        val = FORK_POLL_INTERVAL_DEFAULT
    return max(val, PEER_POLL_INTERVAL)

# mutateの内側でエリア一覧を取り出す共通処理。旧world.peersが残っていればworld.areasへ移し替える
# (両方を残すとareasを消したときに古いpeersが亡霊のように復活するため、peersは必ず捨てる)
def _areas_for_write(settings):
    world = settings.setdefault("world", {})
    raw = world.get("areas")
    if not isinstance(raw, list):
        raw = world.get("peers") if isinstance(world.get("peers"), list) else []
    world.pop("peers", None)
    areas = [{**a, "kind": a.get("kind") or "peer"} for a in raw if isinstance(a, dict)]
    world["areas"] = areas
    return areas

# エリアをマップの空きマスに置く。kindは kinds/ の種別、fieldsは種別ごとの追加フィールド
# (peerならurl/type、youtubeならvideoId)
def add_area(kind, name, fields):
    def mutate(settings):
        areas = _areas_for_write(settings)
        if any(kind.is_duplicate(fields, a) for a in areas):
            return {"error": "duplicate"}
        # 上限は「8マス」。種別をまたいで1つの枠を取り合う
        if len(areas) >= MAX_AREAS:
            return {"error": "full"}
        # 空いているマスからランダムに選んで以降固定。設定に保存するので再起動しても動かない
        used = {a.get("slot") for a in areas}
        area = {"id": secrets.token_hex(4), "kind": kind.key, "name": name,
                "slot": random.choice([s for s in range(MAX_AREAS) if s not in used]), **fields}
        areas.append(area)
        return {"area": area}
    return update_settings(mutate)

def remove_area(area_id):
    def mutate(settings):
        areas = _areas_for_write(settings)
        settings["world"]["areas"] = [a for a in areas if a.get("id") != area_id]
        return next((a for a in areas if a.get("id") == area_id), None)
    return update_settings(mutate)

# 既存エリアの一部フィールドだけを書き換える(動画の差し替えなど)。id/kind/slotは動かさない
def update_area(area_id, fields):
    def mutate(settings):
        areas = _areas_for_write(settings)
        area = next((a for a in areas if a.get("id") == area_id), None)
        if area is None:
            return None
        area.update(fields)
        return area
    return update_settings(mutate)

# fork型ピア(elm200版)向け。GET /api/events はSSEで、接続直後に現在の全状態を
# `data: {...}\n\n` で1回配信してから待機ループに入る仕様(2026-09-13時点で確認)。
# こちらは待機ループには付き合わず、最初の1イベントだけ読んで即座に接続を閉じる
def fetch_fork_snapshot(url):
    req = urllib.request.Request(f"{url}/api/events", headers={"User-Agent": net.USER_AGENT})
    with urllib.request.urlopen(req, timeout=net.TIMEOUT) as res:
        total = 0
        for _ in range(200):  # pingコメント行等を読み飛ばしても無限ループにならないよう上限を設ける
            line = res.readline(2048)
            total += len(line)
            if total > FORK_SSE_MAX:
                raise ValueError("sse event too large")
            if not line:
                raise ValueError("connection closed before snapshot")
            if line.startswith(b"data:"):
                return _json.loads(line[len(b"data:"):].strip().decode("utf-8"))
    raise ValueError("no snapshot event received")

# 失敗してもboard/messagesは前回値を残してok=Falseにするだけ。一瞬の通信断で
# 相手の部屋から人が消えたように見えるのを避ける(クライアント側はグレーアウト表示にする)
def refresh_peer(peer):
    pid, url, peer_type = peer["id"], peer["url"], peer.get("type", "native")
    try:
        if peer_type == "fork":
            snapshot = fetch_fork_snapshot(url)
            board, msgs, config = snapshot.get("board"), snapshot.get("messages"), snapshot.get("config")
            if not isinstance(board, list) or not isinstance(msgs, list) or not isinstance(config, dict):
                raise ValueError("unexpected payload")
            # forkにはネイティブ版のような整数バージョン番号が無いため、部屋画像のファイル名自体を
            # 変化検知用のバージョン代わりに使う(ファイル名が変われば更新とみなす)
            version = config.get("roomImage")
        else:
            board = net.fetch_json(f"{url}/board")
            msgs = net.fetch_json(f"{url}/messages")
            status = net.fetch_json(f"{url}/status")
            if not isinstance(board, list) or not isinstance(msgs, list) or not isinstance(status, dict):
                raise ValueError("unexpected payload")
            version = status.get("roomImageVersion")
        peer_cache[pid] = {"board": board, "messages": msgs,
                           "roomImageVersion": version if isinstance(version, (int, str)) else 0, "ok": True}
    except Exception as e:
        peer_cache[pid] = {**peer_cache.get(pid, {}), "ok": False}
        print(f"[peers] {peer.get('name') or url}: {e}")
        return
    # 画像の取得失敗でピア全体をオフライン扱いにはしない(在室者やチャットは取れているため)
    try:
        refresh_peer_image(pid, url, peer_type, version)
    except Exception as e:
        print(f"[peers] {peer.get('name') or url} の部屋画像: {e}")

# 部屋画像は相手のバージョンが変わったときだけ取り直す(毎回取ると数百KBが巡回のたびに流れる)。
# ただし相手が再起動するとバージョンは0に戻りうるので、それだけに頼らず一定時間で取り直す
def refresh_peer_image(pid, url, peer_type, version):
    cached = area_images.get(pid)
    if cached and cached["version"] == version and time.time() - cached["at"] < PEER_IMAGE_MAX_AGE:
        return
    if peer_type == "fork":
        # forkは部屋画像を public/assets/ 配下から静的配信している(PNG)。versionはそのファイル名
        if not version or not re.fullmatch(r"[\w.-]+", version):
            raise ValueError("invalid room image filename")
        data = net.fetch_bytes(f"{url}/assets/{version}", PEER_IMAGE_MAX)
        if not data.startswith(PNG_MAGIC):
            raise ValueError("not a png image")
        mime = "image/png"
    else:
        data = net.fetch_bytes(f"{url}/room-image.webp", PEER_IMAGE_MAX)
        # 中継するバイト列が本当に画像かは相手任せにせずこちらでも確かめる
        if not is_webp(data):
            raise ValueError("not a webp image")
        mime = "image/webp"
    area_images[pid] = {"data": data, "mime": mime, "version": version, "at": time.time()}

# 在室者やチャットを巡回して取ってくるのはピアだけだが、キャッシュの掃除は全エリアを見て判断する。
# area_imagesはYouTubeエリアのサムネも入っているので、ピアのidだけで掃除すると5秒ごとに
# サムネが捨てられて取り直しのループになる
def poll_peers_once():
    areas = load_areas()
    area_ids = {a.get("id") for a in areas}
    peers = [a for a in areas if a.get("kind") == "peer"]
    peer_ids = {p.get("id") for p in peers}
    # 設定から消えたエリアのキャッシュは捨てる。残すとメモリを食い続けるうえ、
    # 同じURLを付け直したときに取り直す前の古い内容が一瞬見えてしまう
    for aid in [a for a in area_images if a not in area_ids]:
        area_images.pop(aid, None)
    for pid in [p for p in peer_cache if p not in peer_ids]:
        peer_cache.pop(pid, None)
        peer_last_polled.pop(pid, None)
    for key in [k for k in peer_chara_images if k[0] not in peer_ids]:
        peer_chara_images.pop(key, None)
    for key in [k for k in peer_message_images if k[0] not in peer_ids]:
        peer_message_images.pop(key, None)
    # 中継する絵を持つ種別(YouTubeのサムネなど)は、必要なときだけ種別側が取り直す
    for a in areas:
        kind = AREA_KINDS.get(a.get("kind"))
        if not kind or not a.get("id"):
            continue
        try:
            image = kind.refresh_image(a, area_images.get(a["id"]))
        except Exception as e:
            print(f"[areas] {a.get('name') or a['id']} の画像: {e}")
            continue
        if image:
            area_images[a["id"]] = {**image, "at": time.time()}
    # fork型ピアはRedisバックエンドでアクセス1回のコストが高いため、ネイティブ型と同じ5秒間隔では
    # 巡回しない。設定された間隔が経過したものだけを対象に加える
    interval = fork_poll_interval()
    now = time.time()
    targets = []
    for p in peers:
        if not (p.get("id") and p.get("url")):
            continue
        if p.get("type") == "fork":
            if now - peer_last_polled.get(p["id"], 0) < interval:
                continue
            peer_last_polled[p["id"]] = now
        targets.append(p)
    if targets:
        # 応答しないピアが他のピアの鮮度を巻き添えにしないよう並列に取りに行く
        with ThreadPoolExecutor(max_workers=MAX_AREAS) as pool:
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

# チャットに添付された画像。idはメッセージごとに使い捨てで内容が変わらないため、
# チャット画像はバージョンクエリなしで長期キャッシュしてよい
@app.route("/message-image/<image_id>.webp")
def message_image(image_id):
    data = message_images.get(image_id)
    if not data:
        return jsonify({"error": "not found"}), 404
    return Response(data, mimetype="image/webp",
                    headers={"X-Content-Type-Options": "nosniff",
                             "Cache-Control": "public, max-age=86400"})

# エリアのマス絵を中継。ピアなら相手の部屋画像、YouTubeエリアなら動画のサムネイル。
# 実体は取得済みのバイト列なので、ここから外部サーバーに触れることはない。
# 形式がwebp(native)/png(fork)/jpeg(youtube)と分かれるため、拡張子は付けずキャッシュ済みのmimeを返す。
# /room-image-preview と同じくGETに合言葉は載せない方針
@app.route("/area-image/<area_id>")
def area_image(area_id):
    img = area_images.get(area_id)
    if not img or not find_area(area_id):
        return jsonify({"error": "not found"}), 404
    return Response(img["data"], mimetype=img.get("mime", "image/webp"),
                    headers={"X-Content-Type-Options": "nosniff",
                             "Cache-Control": "public, max-age=86400"})

# YouTube NPCのサムネを中継。area_imagesと同じ役割だが、NPCはworld.areasに存在しない
# (boardという別のライフサイクルで管理される)ため、find_areaではなくboardのnpcフラグで存在確認する
@app.route("/npc-image/<npc_id>")
def npc_image(npc_id):
    entry = board.get(npc_id)
    img = npc_images.get(npc_id)
    if not entry or not entry.get("npc") or not img:
        return jsonify({"error": "not found"}), 404
    return Response(img["data"], mimetype=img.get("mime", "image/jpeg"),
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
        quoted_cid = urllib.parse.quote(cid, safe="")
        chara_url = (f"{peer['url']}/api/chara-custom?id={quoted_cid}" if peer.get("type") == "fork"
                     else f"{peer['url']}/chara-custom/{quoted_cid}.png")
        try:
            data = net.fetch_bytes(chara_url, PEER_IMAGE_MAX)
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

# ピア参加者のチャット画像を中継。fork型ピアはメッセージのスキーマが異なり画像URLを持たないため対象外
@app.route("/peer-message-image/<peer_id>/<image_id>.webp")
def peer_message_image(peer_id, image_id):
    peer = find_peer(peer_id)
    if not peer or peer.get("type") == "fork":
        return jsonify({"error": "not found"}), 404
    key = (peer_id, image_id)
    cached = peer_message_images.get(key)
    if not cached:
        quoted_id = urllib.parse.quote(image_id, safe="")
        try:
            data = net.fetch_bytes(f"{peer['url']}/message-image/{quoted_id}.webp", PEER_IMAGE_MAX)
        except Exception:
            return jsonify({"error": "unavailable"}), 502
        # 中継するバイト列が本当に画像かは相手任せにせずこちらでも確かめる
        if not is_webp(data):
            return jsonify({"error": "unavailable"}), 502
        cached = data
        peer_message_images[key] = cached
    return Response(cached, mimetype="image/webp",
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
    room_state = load_settings().get("appearance", {}).get("room_state", "normal")
    return jsonify({"discord": discord, "roomImageVersion": room_image_version, "roomState": room_state})

# マップに置かれたエリアをまとめて返す。ピアについては巡回スレッドが貯めた状態を返すだけで、
# ここから相手サーバーへのアクセスは発生しない(クライアントの2秒pollと5秒巡回は完全に独立)。
# 未認証で開けるので、相手ルームのURLはここには含めない(表示名とnetlocまで)
@app.route("/world")
def get_world():
    areas = []
    for area in load_areas():
        aid = area.get("id")
        # 中継できる絵があるか。取得前にクライアントが404を踏むのを避けるために返す
        common = {"id": aid, "kind": area.get("kind"), "slot": area.get("slot", 0),
                  "hasImage": aid in area_images}
        kind = AREA_KINDS.get(area.get("kind"))
        if kind is None:
            # 知らない種別(settings.jsonの手編集など)。クライアントは霧のマスにする
            areas.append({**common, "name": area.get("name") or ""})
            continue
        entry = {**common, "name": kind.display_name(area), **kind.public_fields(area)}
        # ピアだけは巡回スレッドが貯めた相手の状態を載せる(巡回はまだserver.pyの持ち物)
        if kind.key == "peer":
            cached = peer_cache.get(aid, {})
            entry.update({
                # 未取得はnull(「接続中」表示)、Falseは「接続できません」表示
                "ok": cached.get("ok"),
                "board": cached.get("board", []),
                "messages": cached.get("messages", []),
                "roomImageVersion": cached.get("roomImageVersion", 0),
            })
        areas.append(entry)
    return jsonify({"areas": areas})

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
    image = data.get("image")
    image_id = None
    if image:
        raw = decode_chat_image(image)
        if raw is None:
            return jsonify({"error": "invalid image"}), 400
        image_id = secrets.token_urlsafe(8)
        message_images[image_id] = raw
    if not name or (not text and not image_id):
        return jsonify({"error": "name and text or image required"}), 400
    msg = {
        "name": name,
        "text": text,
        "time": datetime.now().strftime("%H:%M"),
        "ts": time.time(),
    }
    if image_id:
        msg["image"] = image_id
    messages.append(msg)
    post_to_discord(f"**{name}**: {text}" if text else f"**{name}**: (画像)")
    return jsonify(msg), 201

@app.route("/board", methods=["GET"])
def get_board():
    return jsonify(list(board.values()))

# 空いている部屋番号を1つ選ぶ(無ければNone)。人間の入室(join_board)とNPCの入室で
# ロジックを共有することで、両者が同じ部屋番号を取り合わないことを構造的に保証する
def pick_free_room():
    used = {e["room"] for e in board.values()}
    free = [r for r in range(1, ROOM_COUNT + 1) if r not in used]
    return random.choice(free) if free else None

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
        with _board_lock:
            room = pick_free_room()
            if room is None:
                return jsonify({"roomFull": True}), 200
            pose = random.randint(0, 2)
            # 次のpick_free_room()にこの部屋を空きと見せないための仮予約。
            # 下の本書き込みで同じcidのまま完全な内容に上書きされる
            board[cid] = {"id": cid, "room": room, "pose": pose}
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
        admin_suffix = "（管理者）" if is_admin_passphrase((data.get("passphrase") or "").strip()) else ""
        until = f"〜{end}" if end else "〜"
        add_system_message(f"🟢 {name}{admin_suffix} がルーム{room}に入室してもくもく開始({start}{until}): {task}")
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
        add_system_message(f"🚫 {entry['name']} が{admin_label(data)}によりルーム{entry['room']}から強制退室させられました")
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
    add_system_message(f"🖼️ {admin_label(data)}が部屋画像を {filename} に変更しました")
    return jsonify({"ok": True, "file": filename, "version": room_image_version})

# ルームの状態変更の実行: 電気を消したような演出(準備中/Closed)をON/OFFする管理者専用操作
@app.route("/admin/room-state", methods=["POST"])
def admin_set_room_state():
    data = request.get_json()
    supplied = ((data or {}).get("passphrase") or "").strip()
    if not is_admin_passphrase(supplied):
        return jsonify({"error": "admin required"}), 403
    state = (data.get("state") or "").strip()
    if state not in ROOM_STATES:
        return jsonify({"error": "invalid state"}), 400
    set_room_state_setting(state)
    if state == "normal":
        add_system_message(f"💡 {admin_label(data)}がルームの状態を通常に戻しました")
    else:
        add_system_message(f"🚪 {admin_label(data)}がルームを「{ROOM_STATE_LABELS[state]}」にしました")
    return jsonify({"ok": True, "state": state})

# エリア一覧の取得: 管理者合言葉必須(kick/room-imagesと同型のゲート)。
# /world と違って相手ルームのURLも返す(管理画面で「どこにつないでいるか」を確かめるため)
@app.route("/admin/areas", methods=["POST"])
def admin_areas():
    data = request.get_json()
    supplied = ((data or {}).get("passphrase") or "").strip()
    if not is_admin_passphrase(supplied):
        return jsonify({"error": "admin required"}), 403
    areas = [{"id": a.get("id"), "kind": a.get("kind"), "name": a.get("name"),
              "url": a.get("url"), "type": a.get("type", "native"), "videoId": a.get("videoId")}
             for a in load_areas()]
    return jsonify({"areas": areas, "max": MAX_AREAS})

def kind_error(e):
    return jsonify({"error": e.code}), 400

# 中継する絵(YouTubeのサムネなど)を置いた直後からキャッシュに載せる(巡回スレッドの取り直しを待たせないため)
def cache_area_image(area_id, prepared):
    if prepared.image:
        area_images[area_id] = {**prepared.image, "at": time.time()}

# 設置・撤去・差し替えの実行: 一覧取得の成否とは別に、実行時も毎回サーバー側で合言葉を検証する。
# 種別ごとの検証・文言は kinds/ 側に任せ、ここは保存とキャッシュとシステムメッセージだけを受け持つ
@app.route("/admin/area", methods=["POST"])
def admin_area():
    data = request.get_json() or {}
    supplied = (data.get("passphrase") or "").strip()
    if not is_admin_passphrase(supplied):
        return jsonify({"error": "admin required"}), 403
    action = (data.get("action") or "").strip()
    if action == "add":
        kind = AREA_KINDS.get((data.get("kind") or "peer").strip())
        if kind is None:
            return jsonify({"error": "invalid kind"}), 400
        try:
            prepared = kind.prepare(data)
        except KindError as e:
            return kind_error(e)
        result = add_area(kind, prepared.name, prepared.fields)
        if result.get("error") == "duplicate":
            return jsonify({"error": "already connected"}), 400
        if result.get("error") == "full":
            return jsonify({"error": "area limit reached"}), 400
        cache_area_image(result["area"]["id"], prepared)  # idはここで初めて決まる
        add_system_message(kind.placed_text(admin_label(data), prepared.name))
        return jsonify({"ok": True, "area": result["area"], **prepared.response})
    # 差し替えは中身(YouTubeなら動画)だけ。マスの位置(slot)は動かさない
    if action == "update":
        area = find_area((data.get("id") or "").strip())
        kind = AREA_KINDS.get((area or {}).get("kind"))
        if not kind or not kind.updatable:
            return jsonify({"error": "not found"}), 404
        try:
            prepared = kind.prepare(data)
        except KindError as e:
            return kind_error(e)
        update_area(area["id"], {**prepared.fields, "name": prepared.name})
        cache_area_image(area["id"], prepared)
        add_system_message(kind.updated_text(admin_label(data), prepared.name))
        return jsonify({"ok": True, **prepared.response})
    if action == "remove":
        removed = remove_area((data.get("id") or "").strip())
        if removed:
            kind = AREA_KINDS.get(removed.get("kind"))
            name = removed.get("name")
            add_system_message(kind.removed_text(admin_label(data), name) if kind
                               else f"🗑️ {admin_label(data)}が「{name}」を片付けました")
        return jsonify({"ok": True})
    return jsonify({"error": "invalid action"}), 400

# NPCの追加・撤去。実参加者の入退室(join/leave/kick)とは別のライフサイクルとして扱う
# (NPCは自分からは退室しないため、片付けは常にこのエンドポイント経由)。
# 種別ごとの検証は /admin/area と同じ kinds/ の prepare() を使う
@app.route("/admin/npc", methods=["POST"])
def admin_npc():
    data = request.get_json() or {}
    supplied = (data.get("passphrase") or "").strip()
    if not is_admin_passphrase(supplied):
        return jsonify({"error": "admin required"}), 403
    action = (data.get("action") or "").strip()
    if action == "add":
        kind = NPC_KINDS.get((data.get("kind") or "basic").strip())
        if kind is None:
            return jsonify({"error": "invalid kind"}), 400
        try:
            prepared = kind.prepare(data)
        except KindError as e:
            return kind_error(e)
        with _board_lock:
            room = pick_free_room()
            if room is None:
                return jsonify({"roomFull": True}), 200
            cid = f"npc-{secrets.token_hex(4)}"
            while cid in board:
                cid = f"npc-{secrets.token_hex(4)}"
            imgv = 0
            if prepared.chara_image is not None:
                global _img_seq
                _img_seq += 1
                custom_images[cid] = {"data": prepared.chara_image, "v": _img_seq}
                imgv = _img_seq
            board[cid] = {"id": cid, "name": prepared.name, "start": datetime.now().strftime("%H:%M"),
                          "end": "", "task": prepared.task, "room": room,
                          "pose": random.randint(0, 2), "imgv": imgv, "npc": True, "kind": kind.key,
                          **prepared.fields}
            # npc idが決まるのはここなので、中継する絵(YouTubeのサムネ)の登録もここで行う
            if prepared.image:
                npc_images[cid] = prepared.image
        add_system_message(f"🤖 {admin_label(data)}がNPC「{prepared.name}」をルーム{room}に入室させました")
        return jsonify({"ok": True, "npc": board[cid], "embeddable": prepared.response.get("embeddable", True)}), 201
    if action == "remove":
        cid = (data.get("id") or "").strip()
        entry = board.get(cid)
        if not entry or not entry.get("npc"):
            return jsonify({"error": "not found"}), 404
        board.pop(cid, None)
        custom_images.pop(cid, None)
        npc_images.pop(cid, None)
        add_system_message(f"🤖 {admin_label(data)}がNPC「{entry['name']}」をルーム{entry['room']}から片付けました")
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
