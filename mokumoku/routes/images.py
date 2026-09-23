import os
import urllib.parse

from flask import Blueprint, Response, jsonify, request, send_from_directory

from mokumoku import net
from mokumoku.areas import find_area, find_peer
from mokumoku.media import PNG_MAGIC, is_webp
from mokumoku.peers import PEER_IMAGE_MAX, peer_chara_images
from mokumoku.settings import ROOM_IMAGE_DIR, list_room_images, load_settings
from mokumoku.state import area_images, board, custom_images, message_images, npc_images, peer_message_images

# 画像の配信。自サーバーの画像はメモリ/ディスクから、ピアの画像は取りに行って中継する
bp = Blueprint("images", __name__)

# 部屋の画像は config/settings.json の appearance.room_image で差し替え可能(再起動不要)
@bp.route("/room-image.webp")
def room_image():
    path = load_settings().get("appearance", {}).get("room_image") or "assets/room-image-1.webp"
    directory, filename = os.path.split(path)
    return send_from_directory(directory or ".", filename)

# 選択パネル用のプレビュー配信。list_room_images()に含まれるファイル名以外は404にする。
# 画像バイト自体は/room-image.webpと同様に非機密の装飾素材なので認証は課さない
# (GETのURL/クエリに合言葉を乗せる設計はログ等に残るリスクがあり、既存のPOST body方式に反するため)
@bp.route("/room-image-preview/<name>")
def room_image_preview(name):
    if name not in list_room_images():
        return jsonify({"error": "not found"}), 404
    return send_from_directory(ROOM_IMAGE_DIR, name)

@bp.route("/chara-image.png")
def chara_image():
    return send_from_directory("assets", "chara-image-1.png")

# インメモリdictの参照のみ(ファイルシステム非接触)。バージョン付きURLで配信するので長めにキャッシュ可
@bp.route("/chara-custom/<cid>.png")
def chara_custom(cid):
    img = custom_images.get(cid)
    if not img:
        return jsonify({"error": "not found"}), 404
    return Response(img["data"], mimetype="image/png",
                    headers={"X-Content-Type-Options": "nosniff",
                             "Cache-Control": "public, max-age=86400"})

# チャットに添付された画像。idはメッセージごとに使い捨てで内容が変わらないため、
# チャット画像はバージョンクエリなしで長期キャッシュしてよい
@bp.route("/message-image/<image_id>.webp")
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
@bp.route("/area-image/<area_id>")
def area_image(area_id):
    img = area_images.get(area_id)
    if not img or not find_area(area_id):
        return jsonify({"error": "not found"}), 404
    return Response(img["data"], mimetype=img.get("mime", "image/webp"),
                    headers={"X-Content-Type-Options": "nosniff",
                             "Cache-Control": "public, max-age=86400"})

# YouTube NPCのサムネを中継。area_imagesと同じ役割だが、NPCはworld.areasに存在しない
# (boardという別のライフサイクルで管理される)ため、find_areaではなくboardのnpcフラグで存在確認する
@bp.route("/npc-image/<npc_id>")
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
@bp.route("/peer-chara/<peer_id>/<cid>.png")
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
@bp.route("/peer-message-image/<peer_id>/<image_id>.webp")
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
