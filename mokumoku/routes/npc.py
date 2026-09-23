import random
import secrets
from datetime import datetime

from flask import Blueprint, jsonify, request

from mokumoku.auth import admin_label, require_admin
from mokumoku.kinds import NPC_KINDS, KindError
from mokumoku.notify import add_system_message
from mokumoku.routes.world import kind_error
from mokumoku.state import _board_lock, board, custom_images, next_img_seq, npc_images, pick_free_room

bp = Blueprint("npc", __name__)

# NPCの追加・撤去。実参加者の入退室(join/leave/kick)とは別のライフサイクルとして扱う
# (NPCは自分からは退室しないため、片付けは常にこのエンドポイント経由)。
# 種別ごとの検証は /admin/area と同じ kinds/ の prepare() を使う
@bp.route("/admin/npc", methods=["POST"])
def admin_npc():
    data = request.get_json() or {}
    err = require_admin(data)
    if err:
        return err
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
                imgv = next_img_seq()
                custom_images[cid] = {"data": prepared.chara_image, "v": imgv}
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
