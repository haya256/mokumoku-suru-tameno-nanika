import os
import random
import secrets
import time
from datetime import datetime

from flask import Blueprint, jsonify, request

from mokumoku import settings, state
from mokumoku.auth import admin_label, check_passphrase, is_admin_passphrase, require_admin
from mokumoku.media import decode_chara_image, decode_chat_image
from mokumoku.notify import add_system_message, discord_status, post_to_discord
from mokumoku.settings import ROOM_IMAGE_DIR, list_room_images, set_room_image_setting, set_room_state_setting
from mokumoku.state import _board_lock, board, bump_room_image_version, custom_images, message_images, messages, next_img_seq, pick_free_room

# 自分のルーム: チャット・入退室・管理者によるルームの見た目の操作
bp = Blueprint("room", __name__)

# ルームの見た目状態(通常/準備中/Closed)。管理者専用の演出切り替え用
ROOM_STATES = ("normal", "preparing", "closed")
ROOM_STATE_LABELS = {"preparing": "準備中", "closed": "Closed"}  # システムメッセージ表示用

# Discord連携の現在状態: off=URL未設定 / on=設定済み / error=直近の送信が失敗(URL失効など)
@bp.route("/status")
def get_status():
    discord = discord_status()
    room_state = settings.load_settings().get("appearance", {}).get("room_state", "normal")
    return jsonify({"discord": discord, "roomImageVersion": state.room_image_version, "roomState": room_state})

@bp.route("/messages", methods=["GET"])
def get_messages():
    return jsonify(messages)

@bp.route("/messages", methods=["POST"])
def post_message():
    data = request.get_json()
    err = check_passphrase(data)
    if err:
        return err
    name = data.get("name", "").strip()
    text = data.get("text", "").strip()
    image = data.get("image")
    image_id = None
    if image:
        raw = decode_chat_image(image)
        if raw is None:
            return jsonify({"error": "invalid image"}), 400
        image_id = secrets.token_urlsafe(8)
        message_images[image_id] = raw
    if not name or (not text and not image_id):
        return jsonify({"error": "name and text or image required"}), 400
    msg = {
        "name": name,
        "text": text,
        "time": datetime.now().strftime("%H:%M"),
        "ts": time.time(),
    }
    if image_id:
        msg["image"] = image_id
    messages.append(msg)
    post_to_discord(f"**{name}**: {text}" if text else f"**{name}**: (画像)")
    return jsonify(msg), 201

@bp.route("/board", methods=["GET"])
def get_board():
    return jsonify(list(board.values()))

# board はクライアントID(ブラウザごとに固定)をキーに持つ。名前は表示用で変更可
@bp.route("/board/join", methods=["POST"])
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
        custom_images[cid] = {"data": raw, "v": next_img_seq()}
    imgv = custom_images.get(cid, {}).get("v", 0)
    board[cid] = {"id": cid, "name": name, "start": start, "end": end, "task": task, "room": room, "pose": pose, "imgv": imgv}
    if is_new:
        admin_suffix = "（管理者）" if is_admin_passphrase((data.get("passphrase") or "").strip()) else ""
        until = f"〜{end}" if end else "〜"
        add_system_message(f"🟢 {name}{admin_suffix} がルーム{room}に入室してもくもく開始({start}{until}): {task}")
    return jsonify(board[cid]), 201

# クライアントが今保持している合言葉が管理者合言葉と一致するか確認するだけの読み取り専用エンドポイント。
# 一致すればクライアント側で「強制退出」ボタンを表示する(実際の実行権限はkick側でも都度検証する)
@bp.route("/admin/status", methods=["POST"])
def admin_status():
    data = request.get_json()
    supplied = ((data or {}).get("passphrase") or "").strip()
    return jsonify({"isAdmin": is_admin_passphrase(supplied)})

@bp.route("/board/kick", methods=["POST"])
def kick_board():
    data = request.get_json()
    err = require_admin(data)
    if err:
        return err
    cid = (data.get("id") or "").strip()
    entry = board.pop(cid, None)
    custom_images.pop(cid, None)
    if entry:
        add_system_message(f"🚫 {entry['name']} が{admin_label(data)}によりルーム{entry['room']}から強制退室させられました")
    return jsonify({"ok": True})

# 画像一覧取得: 管理者合言葉必須(kickと同型のゲート)。画像バイト自体はroom_image_previewで別途取得させる
@bp.route("/admin/room-images", methods=["POST"])
def admin_room_images():
    data = request.get_json()
    err = require_admin(data)
    if err:
        return err
    current_path = settings.load_settings().get("appearance", {}).get("room_image") or f"{ROOM_IMAGE_DIR}/room-image-1.webp"
    return jsonify({"images": list_room_images(), "current": os.path.basename(current_path)})

# 画像変更の実行: 一覧取得の成否とは別に、実行時も毎回サーバー側で合言葉を検証する
@bp.route("/admin/room-image", methods=["POST"])
def admin_set_room_image():
    data = request.get_json()
    err = require_admin(data)
    if err:
        return err
    filename = (data.get("file") or "").strip()
    if filename not in list_room_images():
        return jsonify({"error": "invalid file"}), 400
    set_room_image_setting(filename)
    version = bump_room_image_version()
    add_system_message(f"🖼️ {admin_label(data)}が部屋画像を {filename} に変更しました")
    return jsonify({"ok": True, "file": filename, "version": version})

# ルームの状態変更の実行: 電気を消したような演出(準備中/Closed)をON/OFFする管理者専用操作
@bp.route("/admin/room-state", methods=["POST"])
def admin_set_room_state():
    data = request.get_json()
    err = require_admin(data)
    if err:
        return err
    state = (data.get("state") or "").strip()
    if state not in ROOM_STATES:
        return jsonify({"error": "invalid state"}), 400
    set_room_state_setting(state)
    if state == "normal":
        add_system_message(f"💡 {admin_label(data)}がルームの状態を通常に戻しました")
    else:
        add_system_message(f"🚪 {admin_label(data)}がルームを「{ROOM_STATE_LABELS[state]}」にしました")
    return jsonify({"ok": True, "state": state})

@bp.route("/board/leave", methods=["POST"])
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
