import pytest

from conftest import ADMIN_PASSPHRASE, PASSPHRASE
from mokumoku import peers, state
from mokumoku.areas import MAX_AREAS


def join(client, cid="u1", name="たろう", task="読書", passphrase=PASSPHRASE, seat=None):
    return client.post("/board/join", json={"id": cid, "name": name, "task": task, "passphrase": passphrase, "seat": seat})


# 入室して入室証を受け取る
def join_seat(client, cid="u1", **kw):
    res = join(client, cid=cid, **kw)
    assert res.status_code == 201
    return res.get_json()["seatToken"]


def leave(client, cid="u1", seat=None):
    return client.post("/board/leave", json={"id": cid, "seat": seat})


def post_message(client, cid="u1", seat=None, text="こんにちは", **extra):
    return client.post("/messages", json={"id": cid, "seat": seat, "text": text, **extra})


def admin_post(client, endpoint, **body):
    return client.post(endpoint, json={"passphrase": ADMIN_PASSPHRASE, **body})


def system_texts(client):
    return [m["text"] for m in client.get("/messages").get_json() if m.get("system")]


# --- 入退室・チャット ---

def test_join_and_leave(client):
    res = join(client)
    assert res.status_code == 201
    entry = res.get_json()
    assert entry["name"] == "たろう" and 1 <= entry["room"] <= 9
    assert [e["id"] for e in client.get("/board").get_json()] == ["u1"]

    res = leave(client, seat=entry["seatToken"])
    assert res.status_code == 200 and "読書" in res.get_json()["record"]
    assert client.get("/board").get_json() == []
    texts = system_texts(client)
    assert any("入室" in t for t in texts) and any("退室" in t for t in texts)


def test_join_requires_passphrase(client):
    assert join(client, passphrase="ちがう").status_code == 401
    assert join(client, passphrase=ADMIN_PASSPHRASE).status_code == 201


def test_rooms_fill_up(client):
    rooms = {join(client, cid=f"u{i}").get_json()["room"] for i in range(9)}
    assert rooms == set(range(1, 10))
    assert join(client, cid="u9").get_json() == {"roomFull": True}


def test_post_message(client):
    seat = join_seat(client)
    # 名前は送られてきた値ではなく入室時の名前になる
    assert post_message(client, seat=seat, name="にせもの").status_code == 201
    last = client.get("/messages").get_json()[-1]
    assert last["text"] == "こんにちは" and last["name"] == "たろう"


def test_post_message_requires_join(client):
    assert post_message(client, cid="nobody").status_code == 403
    admin_post(client, "/admin/npc", action="add", kind="basic", name="NPC", task="見守り")
    npc_id = next(e["id"] for e in client.get("/board").get_json() if e.get("npc"))
    assert post_message(client, cid=npc_id).status_code == 403
    assert leave(client, cid=npc_id).status_code == 403
    seat = join_seat(client)
    leave(client, seat=seat)
    assert post_message(client, seat=seat).status_code == 403


# 入室中の人のIDは/boardで誰でも見られるが、入室証がないとその人として操作できない
def test_seat_prevents_impersonation(client):
    seat_a = join_seat(client, cid="a", name="Aさん")
    seat_b = join_seat(client, cid="b", name="Bさん")
    assert all("seatToken" not in e and "seat" not in e for e in client.get("/board").get_json())
    for seat in (None, "", seat_b):
        assert post_message(client, cid="a", seat=seat).status_code == 403
        assert join(client, cid="a", name="のっとり", seat=seat).status_code == 403
        assert leave(client, cid="a", seat=seat).status_code == 403
    board = {e["id"]: e for e in client.get("/board").get_json()}
    assert board["a"]["name"] == "Aさん"
    # 本人は入室証で編集できる(編集では新しい入室証は発行しない)
    res = join(client, cid="a", name="Aさん2", seat=seat_a)
    assert res.status_code == 201 and "seatToken" not in res.get_json()
    assert post_message(client, cid="a", seat=seat_a).status_code == 201


def test_kicked_seat_is_revoked(client):
    seat = join_seat(client)
    admin_post(client, "/board/kick", id="u1")
    assert post_message(client, seat=seat).status_code == 403
    assert join(client, seat=seat, passphrase="ちがう").status_code == 401


def test_admin_label_uses_actor_name(client):
    join(client)
    admin_post(client, "/admin/area", action="add", kind="clock", name="時計A", actorId="u1")
    assert any("たろう（管理者）" in t for t in system_texts(client))


def test_kick_requires_admin(client):
    join(client)
    assert client.post("/board/kick", json={"id": "u1", "passphrase": PASSPHRASE}).status_code == 403
    assert admin_post(client, "/board/kick", id="u1").status_code == 200
    assert client.get("/board").get_json() == []


# --- エリア(ワールドマップ) ---

AREA_CASES = [
    ({"kind": "clock", "name": "時計A"}, {"name": "時計A"}),
    ({"kind": "calendar", "name": ""}, {"name": "カレンダー"}),
    ({"kind": "youtube", "url": "https://youtu.be/dQw4w9WgXcQ", "name": ""},
     {"name": "テスト動画", "videoId": "dQw4w9WgXcQ", "hasImage": True}),
    ({"kind": "browser", "url": "https://example.com/page?q=1", "name": ""},
     {"name": "example.com", "url": "https://example.com/page?q=1"}),
    ({"kind": "peer", "url": "https://peer.example.com", "name": "となり"},
     {"name": "となり", "ok": None, "board": []}),
]


@pytest.mark.parametrize("body,expected", AREA_CASES, ids=[c[0]["kind"] for c in AREA_CASES])
def test_area_add_and_remove(client, body, expected):
    res = admin_post(client, "/admin/area", action="add", **body)
    assert res.status_code == 200, res.get_json()
    area_id = res.get_json()["area"]["id"]

    areas = client.get("/world").get_json()["areas"]
    assert len(areas) == 1
    assert areas[0]["kind"] == body["kind"] and areas[0]["id"] == area_id
    for key, value in expected.items():
        assert areas[0][key] == value, key
    # 相手ルームのURLは未認証の/worldには出さない
    if body["kind"] == "peer":
        assert "url" not in areas[0]

    listed = admin_post(client, "/admin/areas").get_json()["areas"]
    assert [a["id"] for a in listed] == [area_id]

    assert admin_post(client, "/admin/area", action="remove", id=area_id).status_code == 200
    assert client.get("/world").get_json()["areas"] == []
    assert len(system_texts(client)) == 2  # 設置と撤去


def test_area_requires_admin(client):
    res = client.post("/admin/area", json={"passphrase": PASSPHRASE, "action": "add", "kind": "clock"})
    assert res.status_code == 403


def test_area_invalid_input(client):
    assert admin_post(client, "/admin/area", action="add", kind="peer", url="https://x.example.com/path").status_code == 400
    assert admin_post(client, "/admin/area", action="add", kind="browser", url="ftp://x").status_code == 400
    assert admin_post(client, "/admin/area", action="add", kind="youtube", url="not a video").status_code == 400
    assert admin_post(client, "/admin/area", action="bogus").status_code == 400


def test_area_unknown_kind(client):
    # 以前はpeerとして黙って受け付けていたが、登録簿に無い種別は弾く
    assert admin_post(client, "/admin/area", action="add", kind="nope", url="https://x.example.com").status_code == 400
    # NPC専用の種別はエリアには置けない
    assert admin_post(client, "/admin/area", action="add", kind="basic", name="a", task="b").status_code == 400


def test_poll_refetches_lost_thumbnail(client):
    # 再起動でメモリ上のサムネが消えた状態を再現し、巡回で取り直されることを確かめる
    area_id = admin_post(client, "/admin/area", action="add", kind="youtube",
                         url="https://youtu.be/dQw4w9WgXcQ").get_json()["area"]["id"]
    state.area_images.clear()
    assert client.get(f"/area-image/{area_id}").status_code == 404
    peers.poll_peers_once()
    res = client.get(f"/area-image/{area_id}")
    assert res.status_code == 200 and res.mimetype == "image/jpeg"


def test_area_peer_duplicate(client):
    admin_post(client, "/admin/area", action="add", kind="peer", url="https://peer.example.com")
    res = admin_post(client, "/admin/area", action="add", kind="peer", url="https://peer.example.com")
    assert res.status_code == 400


def test_area_limit(client):
    for i in range(MAX_AREAS):
        assert admin_post(client, "/admin/area", action="add", kind="clock", name=f"c{i}").status_code == 200
    slots = {a["slot"] for a in client.get("/world").get_json()["areas"]}
    assert slots == set(range(MAX_AREAS))
    assert admin_post(client, "/admin/area", action="add", kind="clock").status_code == 400


def test_youtube_area_update(client):
    area_id = admin_post(client, "/admin/area", action="add", kind="youtube",
                         url="https://youtu.be/dQw4w9WgXcQ").get_json()["area"]["id"]
    res = admin_post(client, "/admin/area", action="update", id=area_id,
                     url="https://www.youtube.com/watch?v=aaaaaaaaaaa", name="別の動画")
    assert res.status_code == 200
    area = client.get("/world").get_json()["areas"][0]
    assert area["videoId"] == "aaaaaaaaaaa" and area["name"] == "別の動画"


# --- 部屋NPC ---

NPC_CASES = [
    {"kind": "basic", "name": "ロボ", "task": "見守り"},
    {"kind": "calendar", "name": ""},
    {"kind": "clock", "name": "壁時計"},
    {"kind": "youtube", "url": "https://youtu.be/dQw4w9WgXcQ"},
]


@pytest.mark.parametrize("body", NPC_CASES, ids=[c["kind"] for c in NPC_CASES])
def test_npc_add_and_remove(client, body):
    res = admin_post(client, "/admin/npc", action="add", **body)
    assert res.status_code == 201, res.get_json()
    npc = res.get_json()["npc"]
    assert npc["npc"] is True and npc["kind"] == body["kind"]
    assert [e["id"] for e in client.get("/board").get_json()] == [npc["id"]]
    if body["kind"] == "youtube":
        assert npc["videoId"] == "dQw4w9WgXcQ"
        assert client.get(f"/npc-image/{npc['id']}").status_code == 200

    assert admin_post(client, "/admin/npc", action="remove", id=npc["id"]).status_code == 200
    assert client.get("/board").get_json() == []
    assert npc["id"] not in state.npc_images


def test_npc_invalid(client):
    assert admin_post(client, "/admin/npc", action="add", kind="nope").status_code == 400
    assert admin_post(client, "/admin/npc", action="add", kind="basic", name="名前だけ").status_code == 400
    join(client)
    assert admin_post(client, "/admin/npc", action="remove", id="u1").status_code == 404


# --- ルーム状態・状態取得 ---

def test_room_state(client):
    assert admin_post(client, "/admin/room-state", state="closed").status_code == 200
    assert client.get("/status").get_json()["roomState"] == "closed"
    assert admin_post(client, "/admin/room-state", state="weird").status_code == 400
    admin_post(client, "/admin/room-state", state="normal")


def test_room_title(client):
    assert client.get("/status").get_json()["title"] == "もくもく会"
    assert admin_post(client, "/admin/room-title", title="  夜のもくもく  ").status_code == 200
    assert client.get("/status").get_json()["title"] == "夜のもくもく"
    assert admin_post(client, "/admin/room-title", title="   ").status_code == 400
    assert admin_post(client, "/admin/room-title", title="あ" * 41).status_code == 400
    from mokumoku import settings
    settings.update_settings(lambda s: s["appearance"].pop("title"))


def test_room_passphrase(client):
    res = admin_post(client, "/admin/room-images")
    assert res.get_json()["passphrase"] == PASSPHRASE
    # 今の参加者合言葉を返すのは管理者にだけ。参加者合言葉や合言葉なしでは取れない
    for body in ({}, {"passphrase": PASSPHRASE}):
        res = client.post("/admin/room-images", json=body)
        assert res.status_code == 403 and PASSPHRASE not in res.get_data(as_text=True)
    seat = join_seat(client, cid="before")
    try:
        assert admin_post(client, "/admin/room-passphrase", value="  あたらしい  ").status_code == 200
        # 変更前から入室中の人は入室証で本人確認されるので、聞き直されずに続けられる
        assert post_message(client, cid="before", seat=seat).status_code == 201
        assert join(client, cid="before", seat=seat, passphrase=PASSPHRASE).status_code == 201
        assert leave(client, cid="before", seat=seat).status_code == 200
        assert join(client, cid="before", passphrase=PASSPHRASE).status_code == 401
        assert admin_post(client, "/admin/room-images").get_json()["passphrase"] == "あたらしい"
        assert join(client, passphrase=PASSPHRASE).status_code == 401
        assert join(client, passphrase="あたらしい").status_code == 201
        texts = system_texts(client)
        assert any("参加者合言葉を変更" in t for t in texts) and not any("あたらしい" in t for t in texts)
        assert admin_post(client, "/admin/room-passphrase", value="   ").status_code == 400
        assert admin_post(client, "/admin/room-passphrase", value="あ" * 65).status_code == 400
        assert admin_post(client, "/admin/room-passphrase", value=ADMIN_PASSPHRASE).status_code == 400
        assert client.post("/admin/room-passphrase", json={"passphrase": "あたらしい", "value": "x"}).status_code == 403
    finally:
        admin_post(client, "/admin/room-passphrase", value=PASSPHRASE)


def test_index_served(client, server, monkeypatch):
    # server.pyはindex.htmlを作業ディレクトリから配信するため、テストでは一時的にリポジトリを指す。
    # 設定まで手元の本物(config/settings.json)を読むとタイトルが環境依存になるので、テスト用の設定に固定する
    import os
    from conftest import REPO_ROOT
    from mokumoku import settings
    monkeypatch.setattr(settings, "SETTINGS_FILE", os.path.abspath(settings.SETTINGS_FILE))
    cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        res = client.get("/")
        assert res.status_code == 200 and b"<script" in res.data
        assert "<title>もくもく会</title>" in res.get_data(as_text=True)
    finally:
        os.chdir(cwd)
