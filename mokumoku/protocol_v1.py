"""ワールド接続プロトコル(mokumoco-world) v1 の組み立て。仕様は docs/world-protocol/v1/spec.md。

自分のルームの状態(board/messages/設定)を v1 のスナップショットに読み替える。
旧来の /board /messages /status は旧版のピアのためにそのまま残している(docs/world-protocol/legacy.md)
"""
import os
import re
import time
import urllib.parse
from datetime import datetime

from mokumoku import net, settings, state
from mokumoku.kinds.youtube import YOUTUBE_ID_PATTERN

PROTOCOL = "mokumoco-world"
VERSION = "1.0"
SNAPSHOT_PATH = "/world-api/v1/snapshot"
MIN_POLL_INTERVAL = 5
MESSAGE_LIMIT = 200  # 新しいものから何件返すか(spec §5)

# boardのエントリのうち、在室者の共通項目。NPCはこれ以外のキー(videoIdなど種別ごとのfields)を props に入れる
_OCCUPANT_KEYS = {"id", "name", "task", "start", "end", "room", "pose", "imgv", "npc", "kind"}


def discovery():
    return {
        "protocol": PROTOCOL,
        "name": settings.room_title(),
        "versions": [{"version": VERSION, "snapshot": SNAPSHOT_PATH}],
        "minPollIntervalSec": MIN_POLL_INTERVAL,
        "software": {"name": "mokumoku-suru-tameno-nanika"},
    }


def _occupant(entry):
    cid = entry["id"]
    avatar = None
    img = state.custom_images.get(cid)
    if img:
        avatar = {"url": f"/chara-custom/{cid}.png", "version": str(img["v"]), "mime": "image/png"}
    npc = None
    if entry.get("npc"):
        npc = {"kind": entry.get("kind") or "basic",
               "props": {k: v for k, v in entry.items() if k not in _OCCUPANT_KEYS}}
    return {"id": cid, "name": entry.get("name", ""), "task": entry.get("task", ""),
            "start": entry.get("start", ""), "end": entry.get("end", ""),
            "cell": entry["room"], "pose": entry.get("pose", 0), "avatar": avatar, "npc": npc}


def _message(m):
    image = None
    if m.get("image"):
        image = {"url": f"/message-image/{m['image']}.webp", "mime": "image/webp"}
    return {
        # システムメッセージはidを持たない時期があったので、tsから作って補う
        "id": m.get("id") or f"sys-{int(m.get('ts', 0) * 1000)}",
        "ts": m.get("ts", 0),
        "author": None if m.get("system") else {"name": m.get("name", ""), "uid": m.get("uid")},
        "text": m.get("text", ""),
        "image": image,
        "system": bool(m.get("system")),
    }


def snapshot():
    appearance = settings.load_settings().get("appearance", {})
    # 部屋画像の版はファイル名と変更回数の組。変更回数は再起動で0に戻るので、ファイル名も混ぜて
    # 再起動の前後で別の画像が同じ版に見えないようにする
    image_file = os.path.basename(appearance.get("room_image") or "room-image-1.webp")
    # board/messagesはリクエスト処理中にも書き換わるので、先に写しを取ってから読む
    entries = sorted(list(state.board.values()), key=lambda e: e.get("room", 0))
    msgs = list(state.messages)[-MESSAGE_LIMIT:]
    return {
        "protocol": PROTOCOL,
        "version": VERSION,
        "generatedAt": time.time(),
        "space": {
            "type": "room9",
            "title": settings.room_title(),
            "favicon": settings.room_favicon(),
            "state": appearance.get("room_state", "normal"),
            "closingAt": settings.closing_at(),
            "image": {"url": "/room-image.webp", "version": f"{image_file}:{state.room_image_version}",
                      "mime": "image/webp"},
            # 入室処理の途中(部屋の仮予約だけ済んだ状態)のエントリは名前を持たないので出さない
            "occupants": [_occupant(e) for e in entries if "name" in e],
        },
        "messages": [_message(m) for m in msgs],
    }


# ---- 接続側: 相手の v1 スナップショットを、今の peer_cache の形(旧来の /board /messages と同じ形)に読み替える ----
# 読み替えておけば、画面側(static/js)は相手が旧版か v1 かを気にせずに済む

DISCOVERY_PATH = "/.well-known/mokumoco-world"
SUPPORTED_MAJOR = 1


def _origin(url):
    p = urllib.parse.urlparse(url)
    return (p.scheme, p.netloc)


# 相手の文書に書かれたURLを解決し、相手のルートURLと同じオリジンのときだけ返す(spec §6.2)。
# 違うオリジンを許すと、相手のスナップショットを踏み台に自サーバーから任意のURLへアクセスさせられる
def same_origin_url(root_url, base_url, value):
    if not isinstance(value, str) or not value:
        return None
    resolved = urllib.parse.urljoin(base_url, value)
    if urllib.parse.urlparse(resolved).scheme not in ("http", "https"):
        return None
    return resolved if _origin(resolved) == _origin(root_url) else None


# 相手が v1 を話すかを確かめ、話すならスナップショットのURLと巡回間隔の希望を返す。話さなければNone
def discover(root_url):
    url = root_url + DISCOVERY_PATH
    try:
        doc = net.fetch_json(url)
    except Exception:
        return None
    if not isinstance(doc, dict) or doc.get("protocol") != PROTOCOL or not isinstance(doc.get("versions"), list):
        return None
    for v in doc["versions"]:
        if not isinstance(v, dict) or not isinstance(v.get("version"), str):
            continue
        if v["version"].split(".")[0] != str(SUPPORTED_MAJOR):
            continue
        snapshot_url = same_origin_url(root_url, url, v.get("snapshot"))
        if not snapshot_url:
            return None
        interval = doc.get("minPollIntervalSec")
        return {"snapshot": snapshot_url,
                "minPoll": interval if isinstance(interval, (int, float)) and interval > 0 else MIN_POLL_INTERVAL,
                "name": doc.get("name") if isinstance(doc.get("name"), str) else ""}
    return None


def _str(value, limit=200):
    return value[:limit] if isinstance(value, str) else ""


# 版は画面側でキャッシュバスターとしてURLのクエリに入るので、安全な文字だけに絞る
def _image_ref(root_url, base_url, ref):
    if not isinstance(ref, dict):
        return None, ""
    url = same_origin_url(root_url, base_url, ref.get("url"))
    version = ref.get("version")
    return url, (re.sub(r"[^\w.:-]", "_", version)[:64] if isinstance(version, str) else "")


# NPCの種類ごとの props のうち、こちらの画面で使うものだけを検証して取り出す。
# 知らない種類や props が不正なものは basic(普通のキャラ)として出す(spec §4.2)
def _npc_fields(npc):
    if not isinstance(npc, dict):
        return None
    kind = npc.get("kind")
    props = npc.get("props") if isinstance(npc.get("props"), dict) else {}
    if kind == "youtube":
        video_id = props.get("videoId")
        if isinstance(video_id, str) and YOUTUBE_ID_PATTERN.fullmatch(video_id):
            return {"kind": "youtube", "videoId": video_id}
        return {"kind": "basic"}
    if kind in ("clock", "calendar"):
        return {"kind": kind}
    return {"kind": "basic"}


def normalize_snapshot(root_url, snapshot_url, doc):
    """相手のスナップショットを {"board", "messages", "roomImage", "media"} に読み替える。
    media は中継してよい画像URLの一覧で、/peer-chara/ /peer-message-image/ はここに載ったURLだけを取りに行く"""
    if not isinstance(doc, dict) or doc.get("protocol") != PROTOCOL:
        raise ValueError("not a mokumoco-world snapshot")
    if str(doc.get("version", "")).split(".")[0] != str(SUPPORTED_MAJOR):
        raise ValueError("unsupported version")
    space = doc.get("space")
    if not isinstance(space, dict):
        raise ValueError("space missing")
    media = {}
    room_url, room_version = _image_ref(root_url, snapshot_url, space.get("image"))

    board = []
    # room9以外(知らない空間種別やstream)は在室者を持たない。名前と絵だけのマスになる(spec §4.1)
    occupants = space.get("occupants") if space.get("type") == "room9" else None
    used_cells = set()
    for o in occupants if isinstance(occupants, list) else []:
        if not isinstance(o, dict):
            continue
        cid, cell = _str(o.get("id"), 64), o.get("cell")
        if not cid or not isinstance(cell, int) or not 1 <= cell <= 9 or cell in used_cells:
            continue
        used_cells.add(cell)
        pose = o.get("pose") if isinstance(o.get("pose"), int) and 0 <= o.get("pose") <= 2 else 0
        entry = {"id": cid, "name": _str(o.get("name"), 40), "task": _str(o.get("task")),
                 "start": _str(o.get("start"), 20), "end": _str(o.get("end"), 20),
                 "room": cell, "pose": pose, "imgv": 0}
        avatar_url, avatar_version = _image_ref(root_url, snapshot_url, o.get("avatar"))
        if avatar_url:
            media[("chara", cid)] = avatar_url
            # 画面側はimgvが真のときだけカスタム画像を引く(キャッシュバスターも兼ねる)
            entry["imgv"] = avatar_version or "1"
        npc = _npc_fields(o.get("npc"))
        if npc:
            entry.update({"npc": True, **npc})
        board.append(entry)

    messages = []
    raw_messages = doc.get("messages")
    for m in raw_messages if isinstance(raw_messages, list) else []:
        if not isinstance(m, dict) or not isinstance(m.get("ts"), (int, float)):
            continue
        try:
            hhmm = datetime.fromtimestamp(m["ts"]).strftime("%H:%M")
        except (OverflowError, OSError, ValueError):
            continue
        mid = _str(m.get("id"), 64)
        author = m.get("author") if isinstance(m.get("author"), dict) else {}
        msg = {"id": mid, "name": _str(author.get("name"), 40), "text": _str(m.get("text"), 5000),
               "ts": m["ts"], "time": hhmm}
        if isinstance(author.get("uid"), str):
            msg["uid"] = author["uid"]
        if m.get("system") is True:
            msg["system"] = True
        image_url, _ = _image_ref(root_url, snapshot_url, m.get("image"))
        if image_url and mid:
            # 画面は /peer-message-image/<peer>/<image>.webp を引く。v1では発言idを画像の鍵にする
            media[("message", mid)] = image_url
            msg["image"] = mid
        messages.append(msg)
    messages.sort(key=lambda m: m["ts"])
    return {"board": board, "messages": messages, "media": media,
            "roomImage": {"url": room_url, "version": room_version} if room_url else None}
