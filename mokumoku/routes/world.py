import time

from flask import Blueprint, jsonify, request

from mokumoku.areas import MAX_AREAS, add_area, find_area, load_areas, remove_area, update_area
from mokumoku.auth import admin_label, require_admin
from mokumoku.kinds import AREA_KINDS, KindError
from mokumoku.notify import add_system_message
from mokumoku.peers import peer_public_state
from mokumoku.state import area_images

# ワールドマップ: エリアの一覧と、管理者によるエリアの設置・差し替え・撤去
bp = Blueprint("world", __name__)

# マップに置かれたエリアをまとめて返す。ピアについては巡回スレッドが貯めた状態を返すだけで、
# ここから相手サーバーへのアクセスは発生しない(クライアントの2秒pollと5秒巡回は完全に独立)。
# 未認証で開けるので、相手ルームのURLはここには含めない(表示名とnetlocまで)
@bp.route("/world")
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
        # ピアだけは巡回スレッド(peers.py)が貯めた相手の状態を載せる
        if kind.key == "peer":
            entry.update(peer_public_state(aid))
        areas.append(entry)
    return jsonify({"areas": areas})

# エリア一覧の取得: 管理者合言葉必須(kick/room-imagesと同型のゲート)。
# /world と違って相手ルームのURLも返す(管理画面で「どこにつないでいるか」を確かめるため)
@bp.route("/admin/areas", methods=["POST"])
def admin_areas():
    data = request.get_json()
    err = require_admin(data)
    if err:
        return err
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
@bp.route("/admin/area", methods=["POST"])
def admin_area():
    data = request.get_json() or {}
    err = require_admin(data)
    if err:
        return err
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
