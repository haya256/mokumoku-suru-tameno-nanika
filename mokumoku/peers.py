import json as _json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from mokumoku import net
from mokumoku.areas import MAX_AREAS, load_areas
from mokumoku.kinds import AREA_KINDS
from mokumoku.media import PNG_MAGIC, is_webp
from mokumoku.settings import load_settings
from mokumoku.state import area_images, peer_message_images

# ワールドマップ: 他のもくもくルーム(ピア)の情報を自分のサーバーが取りに行って参加者に中継する。
# ブラウザから相手サーバーを直接叩かせないことで、CORS設定が不要になり、参加者が何人いても
# 相手への負荷が一定になり、参加者のIPが相手に渡らない
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
peer_chara_images = {}  # (peer_id, cid) -> {"data": bytes, "version": str}
peer_last_polled = {}   # peer_id -> 最後に実際に取得を試みた時刻(fork型のみ使う)

# fork型ピアの巡回間隔(秒)。settings.jsonのworld.fork_poll_interval_secで管理者が調整できる
# (再起動不要)。ネイティブ型より短くして相手に負担をかけないよう、下限をPEER_POLL_INTERVALに丸める
def fork_poll_interval():
    try:
        val = int(load_settings().get("world", {}).get("fork_poll_interval_sec", FORK_POLL_INTERVAL_DEFAULT))
    except (TypeError, ValueError):
        val = FORK_POLL_INTERVAL_DEFAULT
    return max(val, PEER_POLL_INTERVAL)

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


# /world でピアのマスに載せる、巡回スレッドが貯めた相手の状態
def peer_public_state(peer_id):
    cached = peer_cache.get(peer_id, {})
    return {
        # 未取得はnull(「接続中」表示)、Falseは「接続できません」表示
        "ok": cached.get("ok"),
        "board": cached.get("board", []),
        "messages": cached.get("messages", []),
        "roomImageVersion": cached.get("roomImageVersion", 0),
    }
