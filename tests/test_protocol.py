import base64
import glob
import json
import os

import pytest
from jsonschema import Draft202012Validator

from conftest import REPO_ROOT
from mokumoku import peers, protocol_v1, state
from test_api import FAKE_WEBP, admin_post, join_seat, post_message

SPEC_DIR = os.path.join(REPO_ROOT, "docs", "world-protocol", "v1")


def validator(name):
    with open(os.path.join(SPEC_DIR, "schemas", f"{name}.schema.json"), encoding="utf-8") as f:
        return Draft202012Validator(json.load(f))


def assert_valid(name, doc):
    errors = [f"{list(e.path)}: {e.message}" for e in validator(name).iter_errors(doc)]
    assert not errors, errors


# 仕様書の例そのものが仕様(スキーマ)に合っていること。未知フィールド入りの例も通る(must-ignore)
@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(SPEC_DIR, "examples", "*.json"))),
                         ids=os.path.basename)
def test_spec_examples_match_schema(path):
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    assert_valid("discovery" if "discovery" in os.path.basename(path) else "snapshot", doc)


def test_discovery(client):
    res = client.get("/.well-known/mokumoco-world")
    assert res.status_code == 200
    doc = res.get_json()
    assert_valid("discovery", doc)
    assert doc["protocol"] == "mokumoco-world"
    assert doc["versions"][0]["snapshot"] == "/world-api/v1/snapshot"


def test_snapshot_empty_room(client):
    doc = client.get("/world-api/v1/snapshot").get_json()
    assert_valid("snapshot", doc)
    assert doc["space"]["type"] == "room9"
    assert doc["space"]["occupants"] == []


def test_snapshot_room_and_chat(client):
    seat = join_seat(client, cid="u1", name="たろう", task="読書")
    image = "data:image/webp;base64," + base64.b64encode(FAKE_WEBP).decode()
    post_message(client, cid="u1", seat=seat, text="こんばんは", image=image)
    admin_post(client, "/admin/npc", action="add", kind="youtube", url="https://youtu.be/dQw4w9WgXcQ")
    admin_post(client, "/admin/npc", action="add", kind="clock", name="壁時計")

    doc = client.get("/world-api/v1/snapshot").get_json()
    assert_valid("snapshot", doc)

    occupants = {o["id"]: o for o in doc["space"]["occupants"]}
    me = occupants["u1"]
    assert (me["name"], me["task"], me["npc"], me["avatar"]) == ("たろう", "読書", None, None)
    assert me["cell"] == state.board["u1"]["room"]
    npcs = {o["npc"]["kind"]: o["npc"] for o in occupants.values() if o["npc"]}
    assert npcs["youtube"]["props"] == {"videoId": "dQw4w9WgXcQ"}
    assert npcs["clock"]["props"] == {}

    msgs = doc["messages"]
    # 入室・NPC設置のお知らせもidを持ち、tsの順に並ぶ
    assert all(m["id"] for m in msgs)
    assert [m["ts"] for m in msgs] == sorted(m["ts"] for m in msgs)
    chat = next(m for m in msgs if not m["system"])
    assert chat["author"] == {"name": "たろう", "uid": "u1"}
    assert chat["text"] == "こんばんは"
    # 画像URLは自サーバーの実在するパス(接続側はスナップショットのURLを基準に解決する)
    assert client.get(chat["image"]["url"]).status_code == 200
    assert all(m["author"] is None for m in msgs if m["system"])


def test_snapshot_avatar_points_to_served_image(client):
    png = b"\x89PNG\r\n\x1a\nfake"
    client.post("/board/join", json={"id": "u2", "name": "はなこ", "task": "絵",
                                     "passphrase": "もくもく",
                                     "image": "data:image/png;base64," + base64.b64encode(png).decode()})
    occupant = client.get("/world-api/v1/snapshot").get_json()["space"]["occupants"][0]
    assert occupant["avatar"]["version"]
    assert client.get(occupant["avatar"]["url"]).data == png


def test_snapshot_message_limit(client):
    for i in range(protocol_v1.MESSAGE_LIMIT + 30):
        state.messages.append({"id": f"m{i}", "name": "x", "text": str(i), "time": "", "ts": float(i)})
    msgs = client.get("/world-api/v1/snapshot").get_json()["messages"]
    assert len(msgs) == protocol_v1.MESSAGE_LIMIT
    assert msgs[-1]["id"] == f"m{protocol_v1.MESSAGE_LIMIT + 29}"


# ---- 接続側 ----
# テスト用サーバー自身を「相手ルーム」に見立てる。PEER_HOSTS宛ての取得をテストクライアントに流す
PEER_HOSTS = ("https://peer.example.com", "https://peer2.example.com")


@pytest.fixture
def loopback(client, monkeypatch):
    from mokumoku import net
    original_bytes = net.fetch_bytes

    def fetch_bytes(url, limit):
        host = next((h for h in PEER_HOSTS if url.startswith(h + "/")), None)
        if host is None:
            return original_bytes(url, limit)
        res = client.get(url[len(host):])
        if res.status_code != 200:
            raise OSError(f"HTTP {res.status_code}")
        return res.data

    monkeypatch.setattr(net, "fetch_bytes", fetch_bytes)
    monkeypatch.setattr(net, "fetch_json", lambda url: json.loads(fetch_bytes(url, net.JSON_MAX)))
    yield client
    peers.peer_cache.clear()
    peers.peer_chara_images.clear()
    state.peer_message_images.clear()


def add_peer(client, url=PEER_HOSTS[0], **body):
    res = admin_post(client, "/admin/area", action="add", kind="peer", url=url, **body)
    assert res.status_code == 200, res.get_json()
    return res.get_json()["area"]


def peer_area(client, area_id):
    return next(a for a in client.get("/world").get_json()["areas"] if a["id"] == area_id)


def test_auto_detects_v1(loopback):
    area = add_peer(loopback)
    assert area["type"] == "v1"
    assert area["snapshot"] == "https://peer.example.com/world-api/v1/snapshot"
    # 表示名を入れなければ相手のDiscoveryの名前になる
    assert area["name"] == "もくもく会"


def test_auto_falls_back_to_native(client):
    # 外部通信禁止のフェイクではDiscoveryが取れない → 旧方式
    res = admin_post(client, "/admin/area", action="add", kind="peer", url="https://old.example.com")
    assert res.get_json()["area"]["type"] == "native"
    res = admin_post(client, "/admin/area", action="add", kind="peer", url="https://old2.example.com", type="v1")
    assert res.status_code == 400 and res.get_json()["error"] == "protocol not found"


def test_v1_peer_relays_room_chat_and_images(loopback):
    png = b"\x89PNG\r\n\x1a\nfake"
    loopback.post("/board/join", json={"id": "u1", "name": "たろう", "task": "読書", "passphrase": "もくもく",
                                       "image": "data:image/png;base64," + base64.b64encode(png).decode()})
    seat = state.seat_tokens["u1"]
    image = "data:image/webp;base64," + base64.b64encode(FAKE_WEBP).decode()
    msg = post_message(loopback, cid="u1", seat=seat, text="こんばんは", image=image).get_json()
    admin_post(loopback, "/admin/npc", action="add", kind="youtube", url="https://youtu.be/dQw4w9WgXcQ")
    area = add_peer(loopback)
    peers.poll_peers_once()

    shown = peer_area(loopback, area["id"])
    assert shown["ok"] is True
    me = next(e for e in shown["board"] if e["id"] == "u1")
    assert (me["name"], me["task"], me["room"]) == ("たろう", "読書", state.board["u1"]["room"])
    tv = next(e for e in shown["board"] if e.get("npc"))
    assert (tv["kind"], tv["videoId"]) == ("youtube", "dQw4w9WgXcQ")

    chat = next(m for m in shown["messages"] if not m.get("system"))
    assert (chat["name"], chat["text"], chat["uid"], chat["ts"]) == ("たろう", "こんばんは", "u1", msg["ts"])
    res = loopback.get(f"/peer-message-image/{area['id']}/{chat['image']}.webp")
    assert res.status_code == 200 and res.data == FAKE_WEBP and res.mimetype == "image/webp"

    res = loopback.get(f"/peer-chara/{area['id']}/u1.png?v={me['imgv']}")
    assert res.status_code == 200 and res.data == png and res.mimetype == "image/png"
    # スナップショットに無い画像は取りに行かない
    assert loopback.get(f"/peer-chara/{area['id']}/nobody.png?v=1").status_code == 404



def test_v1_peer_relays_room_image(loopback):
    area = add_peer(loopback)
    peers.poll_peers_once()
    res = loopback.get(f"/area-image/{area['id']}")
    assert res.status_code == 200 and res.mimetype == "image/webp"
    assert res.data == loopback.get("/room-image.webp").data
    assert peer_area(loopback, area["id"])["roomImageVersion"] == f"room-image-1.webp:{state.room_image_version}"


# 同じ相手を v1 と旧方式でつないだとき、画面に渡る中身(在室者と発言)が揃っていること
def test_v1_matches_native(loopback):
    seat = join_seat(loopback, cid="u1", name="たろう", task="読書")
    post_message(loopback, cid="u1", seat=seat, text="やあ")
    admin_post(loopback, "/admin/npc", action="add", kind="clock", name="壁時計")
    v1 = add_peer(loopback, PEER_HOSTS[0])
    native = add_peer(loopback, PEER_HOSTS[1], type="native")
    peers.poll_peers_once()
    a, b = peer_area(loopback, v1["id"]), peer_area(loopback, native["id"])

    def occupants(area):
        return sorted((e["id"], e["name"], e["task"], e["room"], e["pose"], bool(e.get("npc")), e.get("kind", "basic"))
                      for e in area["board"])

    def chat(area):
        return [(m["name"], m["text"], m["ts"], bool(m.get("system"))) for m in area["messages"]]

    assert occupants(a) == occupants(b)
    assert chat(a) == chat(b)


# ---- 読み替えの頑丈さ(相手は信用しない) ----
ROOT = "https://peer.example.com"
SNAP = ROOT + "/world-api/v1/snapshot"


def load_example(name):
    with open(os.path.join(SPEC_DIR, "examples", name), encoding="utf-8") as f:
        return json.load(f)


def test_normalize_future_minor_ignores_unknowns():
    norm = protocol_v1.normalize_snapshot(ROOT, SNAP, load_example("snapshot-future-minor.json"))
    assert norm["board"] == [{"id": "c-1", "name": "みらい", "task": "", "start": "", "end": "",
                              "room": 1, "pose": 0, "imgv": 0, "npc": True, "kind": "basic"}]
    assert norm["messages"][0]["text"] == "やあ"


def test_normalize_unknown_space_keeps_title_image_only():
    norm = protocol_v1.normalize_snapshot(ROOT, SNAP, load_example("snapshot-unknown-space.json"))
    assert norm["board"] == []
    assert norm["roomImage"] == {"url": ROOT + "/board.png", "version": "88"}


def test_normalize_drops_cross_origin_and_bad_values():
    doc = load_example("snapshot-room9.json")
    occ = doc["space"]["occupants"]
    occ[0]["avatar"]["url"] = "http://169.254.169.254/latest/meta-data"
    occ[1]["cell"] = occ[0]["cell"]  # 部屋の重複は後のほうを捨てる
    occ[2]["npc"]["props"]["videoId"] = "<script>"
    occ[2]["pose"] = 99
    doc["space"]["image"]["url"] = "file:///etc/passwd"
    doc["messages"][2]["image"]["url"] = "//evil.example.com/x.webp"
    norm = protocol_v1.normalize_snapshot(ROOT, SNAP, doc)

    board = {e["id"]: e for e in norm["board"]}
    assert board["c-8f3a"]["imgv"] == 0 and ("chara", "c-8f3a") not in norm["media"]
    assert "c-21bd" not in board
    assert board["npc-1a2b3c4d"]["kind"] == "basic" and "videoId" not in board["npc-1a2b3c4d"]
    assert board["npc-1a2b3c4d"]["pose"] == 0
    assert norm["roomImage"] is None
    assert norm["media"] == {}
    assert "image" not in norm["messages"][2]


def test_normalize_rejects_other_major():
    doc = load_example("snapshot-minimal.json")
    doc["version"] = "2.0"
    with pytest.raises(ValueError):
        protocol_v1.normalize_snapshot(ROOT, SNAP, doc)


def test_v1_poll_interval_respects_min_poll():
    assert peers.peer_poll_interval({"type": "v1", "minPoll": 30}) == 30
    assert peers.peer_poll_interval({"type": "v1", "minPoll": 1}) == peers.PEER_POLL_INTERVAL
    assert peers.peer_poll_interval({"type": "native"}) == peers.PEER_POLL_INTERVAL
