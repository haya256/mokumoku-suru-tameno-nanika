from flask import Blueprint, jsonify

from mokumoku import protocol_v1

# ワールド接続プロトコル(mokumoco-world)の提供側。仕様は docs/world-protocol/。
# 認証なしのGETだけで、ここから外部サーバーへのアクセスは発生しない
bp = Blueprint("protocol", __name__)

@bp.route("/.well-known/mokumoco-world")
def discovery():
    return jsonify(protocol_v1.discovery())

@bp.route(protocol_v1.SNAPSHOT_PATH)
def snapshot_v1():
    res = jsonify(protocol_v1.snapshot())
    res.headers["Cache-Control"] = "no-cache"
    return res
