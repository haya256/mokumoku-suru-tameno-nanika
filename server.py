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
import urllib.error
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
npc_images = {}  # npc board id -> {"data": bytes, "mime": str, "version": str} (YouTube NPCのサムネ)
_img_seq = 0  # キャッシュバスター用の通し番号。退室しても巻き戻さない(再入室時のキャッシュ誤爆防止)
room_image_version = 0  # 部屋画像が変更されるたびに+1(クライアントが変化検知するためだけの値)
MAX_IMAGE_B64 = 700_000
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ROOM_COUNT = 9
NPC_KINDS = ("basic", "calendar", "clock", "youtube")  # 将来 talking/ai_persona 等を足す想定の許可リスト
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
PEER_TIMEOUT = 5
PEER_JSON_MAX = 1_000_000

# 実機のelm200 fork版で確認した部屋画像は1024x1024のPNGで約2.3MBあった(nativeのwebpより大きい)。
# それを弾かない程度の余裕を持たせつつ、無制限にはしない
PEER_IMAGE_MAX = 6_000_000
PEER_IMAGE_MAX_AGE = 300 # 部屋画像を取り直すまでの最長時間(秒)
WEBP_MAGIC_HEAD = b"RIFF"
WEBP_MAGIC_TAIL = b"WEBP"
# fork型ピア(FastAPI+Redisバックエンド、GET /api/events のSSEでスナップショット配信)のデフォルト巡回間隔。
# アクセス1回ごとに相手のRedisコマンドを複数消費するため、インメモリのネイティブ型より長めに取る。
# もくもく会は24時間稼働ではなく限られた時間だけ動かす運用が前提のため、1分程度なら実用上許容範囲。
# config/settings.json の world.fork_poll_interval_sec で管理者が調整できる(再起動不要)
FORK_POLL_INTERVAL_DEFAULT = 60
FORK_SSE_MAX = 2_000_000  # SSEの最初の1イベントを読む際の上限バイト数(以降は読まず切断する)

# YouTubeエリア: 管理者が指定した動画1本を置けるマス。サムネイルは部屋画像と同じく自サーバーが中継し、
# 参加者が再生ボタンを押すまでブラウザはYouTubeと通信しない(=勝手に再生が始まらない)
# 動画IDは必ずASCII限定で検証する。Pythonの \w はUnicodeマッチなので全角文字が通ってしまう
YOUTUBE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{11}")
YOUTUBE_THUMB_MAX = 1_000_000  # 実測で最大のmaxresdefaultでも100KB弱。部屋画像の6MB枠を使い回す必要はない
JPEG_MAGIC = b"\xff\xd8"

# 時計エリア: サーバーが持つのは名前だけ。時刻は見ている人のブラウザのローカル時刻を
# クライアントがそのまま描く(サーバーの時刻でもタイムゾーン指定でもない)ので、
# 巡回もキャッシュも中継する絵も一切要らない
DEFAULT_CLOCK_NAME = "時計"

# カレンダーエリア: 時計と同じくサーバーが持つのは名前だけ。日付は見ている人のブラウザの
# ローカル日付をそのまま描く(サーバーの日付でもタイムゾーン指定でもない)ので、
# 巡回もキャッシュも中継する絵も一切要らない
DEFAULT_CALENDAR_NAME = "カレンダー"

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

PEER_TYPES = ("native", "fork")  # native: このリポジトリ系統(Flask+ポーリング) / fork: elm200版(FastAPI+Redis+SSE)

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

# ブラウザエリア用。peerと違い任意のページを指すのでパス・クエリ・フラグメントを許可する
def normalize_iframe_url(url):
    url = (url or "").strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return url

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

# エリアをマップの空きマスに置く。extraには種別ごとの追加フィールドを渡す
# (peerならurl/type、youtubeならvideoId)
def add_area(kind, name, extra):
    def mutate(settings):
        areas = _areas_for_write(settings)
        # 同じ相手ルームを二重に登録させない。youtubeエリアはurlを持たないので対象外
        # (peer同士の比較に限定しないと、url無し同士がNone==Noneで重複と誤判定される)
        if kind == "peer" and any(a.get("kind") == "peer" and a.get("url") == extra.get("url") for a in areas):
            return {"error": "duplicate"}
        # 上限は「8マス」。種別をまたいで1つの枠を取り合う
        if len(areas) >= MAX_AREAS:
            return {"error": "full"}
        # 空いているマスからランダムに選んで以降固定。設定に保存するので再起動しても動かない
        used = {a.get("slot") for a in areas}
        area = {"id": secrets.token_hex(4), "kind": kind, "name": name,
                "slot": random.choice([s for s in range(MAX_AREAS) if s not in used]), **extra}
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

# YouTubeの各種URL形式(watch?v=, youtu.be/, shorts/, embed/)、または生の動画IDから11文字のIDを取り出す。
# index.htmlのextractYouTubeId()と同じ判定をサーバー側でもやる(クライアントの検証は当てにしない)
def extract_youtube_id(value):
    value = (value or "").strip()
    if not value:
        return None
    ok = lambda s: s if YOUTUBE_ID_PATTERN.fullmatch(s or "") else None
    if "/" not in value and "?" not in value:
        return ok(value)  # 生のIDを直接貼られた場合
    try:
        u = urllib.parse.urlparse(value if "//" in value else f"https://{value}")
    except ValueError:
        return None
    host = (u.hostname or "").removeprefix("www.").removeprefix("m.")
    if host == "youtu.be":
        return ok(u.path.lstrip("/").split("/")[0])
    if host in ("youtube.com", "youtube-nocookie.com"):
        if u.path == "/watch":
            return ok(urllib.parse.parse_qs(u.query).get("v", [""])[0])
        m = re.fullmatch(r"/(?:shorts|embed|live)/([^/]+)", u.path)
        if m:
            return ok(m.group(1))
    return None

# サムネイルは自サーバーが取得して参加者に中継する(部屋画像と同じ流儀)。動画IDは検証済みなので
# パスに記号が混ざることはなく、組み立て先はi.ytimg.comの決め打ちパスに固定される。
# hqdefault(480x360)は必ずあるが4:3で上下に黒帯が焼き込まれているため使わない。16:9のものを
# 大きい順に試し、maxresdefault(1280x720)が無ければmqdefault(320x180)に落とす
YOUTUBE_THUMB_NAMES = ("maxresdefault.jpg", "mqdefault.jpg")

def fetch_youtube_thumbnail(video_id):
    last_error = None
    for name in YOUTUBE_THUMB_NAMES:
        try:
            data = fetch_peer_bytes(f"https://i.ytimg.com/vi/{video_id}/{name}", YOUTUBE_THUMB_MAX)
        except Exception as e:
            last_error = e
            continue
        # 中継するバイト列が本当に画像かは相手任せにせずこちらでも確かめる
        if not data.startswith(JPEG_MAGIC):
            last_error = ValueError("not a jpeg image")
            continue
        return data
    raise last_error or ValueError("no thumbnail available")

# 動画タイトルをoEmbedから取る(APIキー不要)。表示名が未指定のときのフォールバックに使うだけなので、
# 取れなくても機能は成立する。埋め込み禁止・非公開の動画はここが401/404になるので事前警告にも使える
def fetch_youtube_title(video_id):
    watch_url = urllib.parse.quote(f"https://www.youtube.com/watch?v={video_id}", safe="")
    info = fetch_peer_json(f"https://www.youtube.com/oembed?url={watch_url}&format=json")
    # タイトルはシステムメッセージとDiscordにも載るので、ピア名と同じく改行を潰して長さを切る。
    # 切った拍子に開き括弧だけが残ると尻切れ感が強いので、末尾の区切り文字はまとめて落とす
    return " ".join(str(info.get("title") or "").split())[:40].rstrip(" -–—([{「『【（").strip() or None

# ブラウザエリア用。埋め込み可否のベストエフォート判定。X-Frame-Options/CSPで「明らかに拒否」と
# 分かる場合だけFalseにし、それ以外(判定不能・通信失敗・ドメイン限定のframe-ancestors等)はTrue側に
# 倒す。誤って「埋め込めない」と警告して置くのを迷わせるより、置けた後に気づく方がましという判断
def check_iframe_embeddable(url):
    req = urllib.request.Request(url, headers={"User-Agent": "mokumoku-bot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=PEER_TIMEOUT) as res:
            headers = res.headers
    except urllib.error.HTTPError as e:
        headers = e.headers
    except Exception:
        return True
    if (headers.get("X-Frame-Options") or "").strip().lower() in ("deny", "sameorigin"):
        return False
    for directive in (headers.get("Content-Security-Policy") or "").split(";"):
        parts = directive.strip().split()
        if parts and parts[0].lower() == "frame-ancestors":
            values = [v.lower() for v in parts[1:]]
            if not values or values in (["'none'"], ["'self'"]):
                return False
    return True

# サムネをキャッシュに載せる。versionに動画IDを入れておくと、差し替え時だけ取り直せる
def refresh_youtube_thumbnail(area_id, video_id):
    # settings.jsonを手編集された場合に備えて、取りに行く前にIDの形を確かめる
    if not YOUTUBE_ID_PATTERN.fullmatch(video_id or ""):
        raise ValueError("invalid video id")
    cached = area_images.get(area_id)
    # ピアの部屋画像と違い相手が黙って中身を差し替えることはないので、PEER_IMAGE_MAX_AGEの
    # 期限切れ再取得は当てない(5分ごとに無意味にytimgを叩かないため)
    if cached and cached["version"] == video_id:
        return
    area_images[area_id] = {"data": fetch_youtube_thumbnail(video_id), "mime": "image/jpeg",
                            "version": video_id, "at": time.time()}

# fork型ピア(elm200版)向け。GET /api/events はSSEで、接続直後に現在の全状態を
# `data: {...}\n\n` で1回配信してから待機ループに入る仕様(2026-09-13時点で確認)。
# こちらは待機ループには付き合わず、最初の1イベントだけ読んで即座に接続を閉じる
def fetch_fork_snapshot(url):
    req = urllib.request.Request(f"{url}/api/events", headers={"User-Agent": "mokumoku-bot/1.0"})
    with urllib.request.urlopen(req, timeout=PEER_TIMEOUT) as res:
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
            board = fetch_peer_json(f"{url}/board")
            msgs = fetch_peer_json(f"{url}/messages")
            status = fetch_peer_json(f"{url}/status")
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
        data = fetch_peer_bytes(f"{url}/assets/{version}", PEER_IMAGE_MAX)
        if not data.startswith(PNG_MAGIC):
            raise ValueError("not a png image")
        mime = "image/png"
    else:
        data = fetch_peer_bytes(f"{url}/room-image.webp", PEER_IMAGE_MAX)
        # 中継するバイト列が本当に画像かは相手任せにせずこちらでも確かめる
        if data[:4] != WEBP_MAGIC_HEAD or data[8:12] != WEBP_MAGIC_TAIL:
            raise ValueError("not a webp image")
        mime = "image/webp"
    area_images[pid] = {"data": data, "mime": mime, "version": version, "at": time.time()}

# 巡回して外から取ってくる必要があるのはピアだけだが、キャッシュの掃除は全エリアを見て判断する。
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
    # YouTubeエリアのサムネは設置・差し替え時に同期取得しているので、ここに残るのは
    # 「サーバーを再起動してインメモリのキャッシュが消えた」場合の取り直しだけ
    for a in areas:
        if a.get("kind") != "youtube" or not a.get("id"):
            continue
        try:
            refresh_youtube_thumbnail(a["id"], a.get("videoId"))
        except Exception as e:
            print(f"[areas] {a.get('name') or a['id']} のサムネイル: {e}")
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
            data = fetch_peer_bytes(chara_url, PEER_IMAGE_MAX)
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
        if area.get("kind") == "youtube":
            areas.append({**common, "name": area.get("name") or "YouTube",
                          "videoId": area.get("videoId")})
            continue
        # 時計はサーバーから渡すものが名前しかない(時刻は見ている人のブラウザが出す)
        if area.get("kind") == "clock":
            areas.append({**common, "name": area.get("name") or DEFAULT_CLOCK_NAME})
            continue
        # カレンダーも時計と同じく、サーバーから渡すものが名前しかない
        if area.get("kind") == "calendar":
            areas.append({**common, "name": area.get("name") or DEFAULT_CALENDAR_NAME})
            continue
        # ブラウザはサーバーが名前とURLを持つが、ページの中身には一切関与しない
        # (iframeは参加者のブラウザが直接読む)。peerと違いURLをそのまま返す
        if area.get("kind") == "browser":
            areas.append({**common, "name": area.get("name") or urllib.parse.urlparse(area.get("url") or "").netloc,
                          "url": area.get("url")})
            continue
        cached = peer_cache.get(aid, {})
        areas.append({
            **common,
            "name": area.get("name") or urllib.parse.urlparse(area.get("url", "")).netloc,
            # 未取得はnull(「接続中」表示)、Falseは「接続できません」表示
            "ok": cached.get("ok"),
            "board": cached.get("board", []),
            "messages": cached.get("messages", []),
            "roomImageVersion": cached.get("roomImageVersion", 0),
        })
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

# YouTubeエリアを置くときの共通処理。サムネとタイトルはここで同期的に取りに行く。
# 巡回スレッド任せにすると、置いた直後の数秒間マスが空白になるうえ、動画を差し替えたときに
# 新しいキャッシュバスターURLで古いサムネが返り、Cache-Controlの24時間がブラウザに焼き付いてしまう
def prepare_youtube_area(data):
    video_id = extract_youtube_id(data.get("url") or data.get("videoId"))
    if not video_id:
        return None, (jsonify({"error": "invalid video"}), 400)
    # 削除済み・限定公開などサムネイルすら取れない動画は、置いても意味がないのでここで弾く
    try:
        thumbnail = fetch_youtube_thumbnail(video_id)
    except Exception as e:
        print(f"[areas] サムネイル取得に失敗: {e}")
        return None, (jsonify({"error": "video unavailable"}), 400)
    # oEmbedは埋め込みを禁止している動画に401を返すので、タイトルが要らない場合でも必ず叩いて
    # 「置けたのに再生できない」を事前に警告する。ただし通信の一時的な失敗と区別が付かないため、
    # 設置自体は止めない(サムネが取れている以上、動画そのものは存在している)
    title = None
    try:
        title = fetch_youtube_title(video_id)
    except Exception as e:
        print(f"[areas] タイトル取得に失敗: {e}")
    # 名前はシステムメッセージとDiscordにも載るので、改行を潰して長さを切る
    name = " ".join((data.get("name") or "").split())[:40] or title
    return {"videoId": video_id, "name": name or "YouTube", "thumbnail": thumbnail,
            "embeddable": title is not None}, None

# 取得済みのサムネをそのエリアのキャッシュに載せる(巡回スレッドの取り直しを待たせないため)
def cache_youtube_thumbnail(area_id, prepared):
    area_images[area_id] = {"data": prepared["thumbnail"], "mime": "image/jpeg",
                            "version": prepared["videoId"], "at": time.time()}

# 設置・撤去・差し替えの実行: 一覧取得の成否とは別に、実行時も毎回サーバー側で合言葉を検証する
@app.route("/admin/area", methods=["POST"])
def admin_area():
    data = request.get_json() or {}
    supplied = (data.get("passphrase") or "").strip()
    if not is_admin_passphrase(supplied):
        return jsonify({"error": "admin required"}), 403
    action = (data.get("action") or "").strip()
    kind = (data.get("kind") or "peer").strip()
    if action == "add" and kind == "youtube":
        prepared, error = prepare_youtube_area(data)
        if error:
            return error
        result = add_area("youtube", prepared["name"], {"videoId": prepared["videoId"]})
        if result.get("error") == "full":
            return jsonify({"error": "area limit reached"}), 400
        cache_youtube_thumbnail(result["area"]["id"], prepared)  # idはここで初めて決まる
        add_system_message(f"📺 管理者がYouTubeルーム「{prepared['name']}」を置きました")
        return jsonify({"ok": True, "area": result["area"], "embeddable": prepared["embeddable"]})
    # 時計は外から取ってくるものが何も無いので、名前を整えて置くだけ。
    # peerの分岐より前に置くこと(下の add はpeerのフォールバックなので、URLを要求されてしまう)
    if action == "add" and kind == "clock":
        name = " ".join((data.get("name") or "").split())[:40] or DEFAULT_CLOCK_NAME
        result = add_area("clock", name, {})
        if result.get("error") == "full":
            return jsonify({"error": "area limit reached"}), 400
        add_system_message(f"🕐 管理者が時計「{name}」を置きました")
        return jsonify({"ok": True, "area": result["area"]})
    # カレンダーも外から取ってくるものが何も無い。peerの分岐より前に置くこと
    if action == "add" and kind == "calendar":
        name = " ".join((data.get("name") or "").split())[:40] or DEFAULT_CALENDAR_NAME
        result = add_area("calendar", name, {})
        if result.get("error") == "full":
            return jsonify({"error": "area limit reached"}), 400
        add_system_message(f"📅 管理者がカレンダー「{name}」を置きました")
        return jsonify({"ok": True, "area": result["area"]})
    # ブラウザは任意ページなのでpeerと違いパス・クエリを許可する専用バリデータを使う。
    # peerの分岐より前に置くこと(下の add はpeerのフォールバックなので、URL形式チェックが
    # 厳しくなり種別も勝手にpeerへ書き換わってしまう)
    if action == "add" and kind == "browser":
        url = normalize_iframe_url(data.get("url"))
        if not url:
            return jsonify({"error": "invalid url"}), 400
        name = " ".join((data.get("name") or "").split())[:40] or urllib.parse.urlparse(url).netloc
        embeddable = check_iframe_embeddable(url)
        result = add_area("browser", name, {"url": url})
        if result.get("error") == "full":
            return jsonify({"error": "area limit reached"}), 400
        add_system_message(f"🌐 管理者がブラウザ「{name}」を置きました")
        return jsonify({"ok": True, "area": result["area"], "embeddable": embeddable})
    if action == "add":
        url = normalize_peer_url(data.get("url"))
        if not url:
            return jsonify({"error": "invalid url"}), 400
        name = " ".join((data.get("name") or "").split())[:40] or urllib.parse.urlparse(url).netloc
        peer_type = data.get("type") if data.get("type") in PEER_TYPES else "native"
        result = add_area("peer", name, {"url": url, "type": peer_type})
        if result.get("error") == "duplicate":
            return jsonify({"error": "already connected"}), 400
        if result.get("error") == "full":
            return jsonify({"error": "area limit reached"}), 400
        add_system_message(f"🌏 管理者が「{name}」とつながりました")
        return jsonify({"ok": True, "area": result["area"]})
    # 差し替えは今のところYouTubeエリアの動画だけ。マスの位置(slot)は動かさない
    if action == "update":
        area = find_area((data.get("id") or "").strip())
        if not area or area.get("kind") != "youtube":
            return jsonify({"error": "not found"}), 404
        prepared, error = prepare_youtube_area(data)
        if error:
            return error
        update_area(area["id"], {"videoId": prepared["videoId"], "name": prepared["name"]})
        cache_youtube_thumbnail(area["id"], prepared)
        add_system_message(f"📺 管理者がYouTubeルームの動画を「{prepared['name']}」に変えました")
        return jsonify({"ok": True, "embeddable": prepared["embeddable"]})
    if action == "remove":
        removed = remove_area((data.get("id") or "").strip())
        if removed and removed.get("kind") == "youtube":
            add_system_message(f"📺 管理者がYouTubeルーム「{removed.get('name')}」を片付けました")
        elif removed and removed.get("kind") == "clock":
            add_system_message(f"🕐 管理者が時計「{removed.get('name')}」を片付けました")
        elif removed and removed.get("kind") == "calendar":
            add_system_message(f"📅 管理者がカレンダー「{removed.get('name')}」を片付けました")
        elif removed and removed.get("kind") == "browser":
            add_system_message(f"🌐 管理者がブラウザ「{removed.get('name')}」を片付けました")
        elif removed:
            add_system_message(f"🌏 管理者が「{removed.get('name')}」との接続を解除しました")
        return jsonify({"ok": True})
    return jsonify({"error": "invalid action"}), 400

# 基本NPC: 名前・やること・画像(任意)を管理者がその都度自由入力する。
# 将来kindが増えたら、この関数と同じ形で prepare_xxx_npc() を追加し、admin_npc()の分岐に足すだけでよい
def prepare_basic_npc(data):
    name = " ".join((data.get("name") or "").split())[:40]
    task = " ".join((data.get("task") or "").split())[:80]
    if not name or not task:
        return None, (jsonify({"error": "name and task required"}), 400)
    raw = None
    image = data.get("image")
    if image:
        raw = decode_chara_image(image)
        if raw is None:
            return None, (jsonify({"error": "invalid image"}), 400)
    return {"name": name, "task": task, "raw": raw}, None

# カレンダーNPC: ワールドマップのカレンダーエリアと同じく、サーバーが持つのは名前だけ。
# 日付は見ている人のブラウザのローカル日付をクライアントがそのまま描くので、taskや画像は扱わない
def prepare_calendar_npc(data):
    name = " ".join((data.get("name") or "").split())[:40] or DEFAULT_CALENDAR_NAME
    return {"name": name, "task": "", "raw": None}, None

# 時計NPC: カレンダーNPCと同じく、サーバーが持つのは名前だけ。時刻は見ている人のブラウザの
# ローカル時刻をクライアントがそのまま描くので、taskや画像は扱わない
def prepare_clock_npc(data):
    name = " ".join((data.get("name") or "").split())[:40] or DEFAULT_CLOCK_NAME
    return {"name": name, "task": "", "raw": None}, None

# YouTube NPC: 動画1本を持つNPC。動画IDの検証・サムネ取得・埋め込み可否チェックは
# 既存のprepare_youtube_area()をそのまま再利用する。サムネの実体(npc_images)はadmin_npc()側で
# 登録する(npc idが決まるのはboard[cid]作成時のため、この関数の時点ではまだ存在しない)
def prepare_youtube_npc(data):
    prepared, error = prepare_youtube_area(data)
    if error:
        return None, error
    return {"name": prepared["name"], "task": "", "raw": None,
            "videoId": prepared["videoId"], "thumbnail": prepared["thumbnail"],
            "embeddable": prepared["embeddable"]}, None

NPC_PREPARERS = {"basic": prepare_basic_npc, "calendar": prepare_calendar_npc, "clock": prepare_clock_npc,
                 "youtube": prepare_youtube_npc}

# NPCの追加・撤去。実参加者の入退室(join/leave/kick)とは別のライフサイクルとして扱う
# (NPCは自分からは退室しないため、片付けは常にこのエンドポイント経由)。
# /admin/area と同じくaction+kindで振る舞いを切り替える形にしておき、将来のkind追加に備える
@app.route("/admin/npc", methods=["POST"])
def admin_npc():
    data = request.get_json() or {}
    supplied = (data.get("passphrase") or "").strip()
    if not is_admin_passphrase(supplied):
        return jsonify({"error": "admin required"}), 403
    action = (data.get("action") or "").strip()
    kind = (data.get("kind") or "basic").strip()
    if action == "add":
        if kind not in NPC_KINDS:
            return jsonify({"error": "invalid kind"}), 400
        prepared, error = NPC_PREPARERS[kind](data)
        if error:
            return error
        with _board_lock:
            room = pick_free_room()
            if room is None:
                return jsonify({"roomFull": True}), 200
            cid = f"npc-{secrets.token_hex(4)}"
            while cid in board:
                cid = f"npc-{secrets.token_hex(4)}"
            imgv = 0
            if prepared["raw"] is not None:
                global _img_seq
                _img_seq += 1
                custom_images[cid] = {"data": prepared["raw"], "v": _img_seq}
                imgv = _img_seq
            board[cid] = {"id": cid, "name": prepared["name"], "start": datetime.now().strftime("%H:%M"),
                          "end": "", "task": prepared["task"], "room": room,
                          "pose": random.randint(0, 2), "imgv": imgv, "npc": True, "kind": kind}
            if "videoId" in prepared:
                board[cid]["videoId"] = prepared["videoId"]
                npc_images[cid] = {"data": prepared["thumbnail"], "mime": "image/jpeg",
                                    "version": prepared["videoId"]}
        add_system_message(f"🤖 管理者がNPC「{prepared['name']}」をルーム{room}に入室させました")
        return jsonify({"ok": True, "npc": board[cid], "embeddable": prepared.get("embeddable", True)}), 201
    if action == "remove":
        cid = (data.get("id") or "").strip()
        entry = board.get(cid)
        if not entry or not entry.get("npc"):
            return jsonify({"error": "not found"}), 404
        board.pop(cid, None)
        custom_images.pop(cid, None)
        npc_images.pop(cid, None)
        add_system_message(f"🤖 管理者がNPC「{entry['name']}」をルーム{entry['room']}から片付けました")
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
