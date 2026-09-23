import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASSPHRASE = "もくもく"
ADMIN_PASSPHRASE = "かんりしゃ"
FAKE_JPEG = b"\xff\xd8fake-jpeg"


def _fake_fetch_bytes(url, limit):
    if "i.ytimg.com" in url:
        return FAKE_JPEG
    raise OSError(f"テスト中の外部通信は禁止: {url}")


def _fake_fetch_json(url):
    if "youtube.com/oembed" in url:
        return {"title": "テスト動画"}
    raise OSError(f"テスト中の外部通信は禁止: {url}")


# server.pyは設定・画像を相対パスで読み、読み込んだ瞬間に巡回スレッドを起動する。
# 本物のconfig/settings.jsonのピアへ通信しないよう、一時ディレクトリへ移ってから読み込む
@pytest.fixture(scope="session")
def server(tmp_path_factory):
    workdir = tmp_path_factory.mktemp("server")
    (workdir / "config").mkdir()
    (workdir / "config" / "合言葉.txt").write_text(PASSPHRASE, encoding="utf-8")
    (workdir / "config" / "管理者合言葉.txt").write_text(ADMIN_PASSPHRASE, encoding="utf-8")
    (workdir / "config" / "settings.json").write_text(json.dumps({"security": {"mode": "very_easy"}}), encoding="utf-8")
    (workdir / "assets").mkdir()
    os.chdir(workdir)
    sys.path.insert(0, REPO_ROOT)
    import server as srv
    srv.fetch_peer_bytes = _fake_fetch_bytes
    srv.fetch_peer_json = _fake_fetch_json
    srv.check_iframe_embeddable = lambda url: True
    return srv


# テストごとにメモリ上の状態とエリア設定を空に戻す
@pytest.fixture
def client(server):
    server.messages.clear()
    server.board.clear()
    server.custom_images.clear()
    server.npc_images.clear()
    server.message_images.clear()
    server.area_images.clear()
    server.update_settings(lambda s: s.setdefault("world", {}).update({"areas": []}))
    return server.app.test_client()
