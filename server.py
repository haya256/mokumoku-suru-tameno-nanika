import os
import random
import urllib.request
import json as _json
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime

app = Flask(__name__)
messages = []
board = {}
ROOM_COUNT = 9
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

def post_to_discord(content):
    if not DISCORD_WEBHOOK_URL:
        return
    payload = _json.dumps({"content": content}).encode()
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "mokumoku-bot/1.0"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[Discord] error: {e}")

def add_system_message(text):
    messages.append({
        "name": "",
        "text": text,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "system": True,
    })
    post_to_discord(text)

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/room-image.png")
def room_image():
    return send_from_directory("assets", "room-image-1.png")

@app.route("/chara-image.png")
def chara_image():
    return send_from_directory("assets", "chara-image-1.png")

@app.route("/messages", methods=["GET"])
def get_messages():
    return jsonify(messages)

@app.route("/messages", methods=["POST"])
def post_message():
    data = request.get_json()
    name = data.get("name", "").strip()
    text = data.get("text", "").strip()
    if not name or not text:
        return jsonify({"error": "name and text required"}), 400
    msg = {
        "name": name,
        "text": text,
        "time": datetime.now().strftime("%H:%M"),
    }
    messages.append(msg)
    post_to_discord(f"**{name}**: {text}")

    task = data.get("task", "").strip()
    if task:
        start = data.get("start", "").strip() or datetime.now().strftime("%H:%M")
        end = data.get("end", "").strip()
        is_new = name not in board
        if is_new:
            used = {e["room"] for e in board.values()}
            free = [r for r in range(1, ROOM_COUNT + 1) if r not in used]
            if not free:
                return jsonify({**msg, "roomFull": True}), 201
            room = random.choice(free)
            pose = random.randint(0, 2)
        else:
            room = board[name]["room"]
            pose = board[name]["pose"]
        board[name] = {"name": name, "start": start, "end": end, "task": task, "room": room, "pose": pose}
        if is_new:
            until = f"〜{end}" if end else "〜"
            add_system_message(f"🟢 {name} がルーム{room}に入室してもくもく開始({start}{until}): {task}")

    return jsonify(msg), 201

@app.route("/board", methods=["GET"])
def get_board():
    return jsonify(list(board.values()))

@app.route("/board/end", methods=["POST"])
def end_board():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    entry = board.pop(name, None)
    if entry:
        add_system_message(f"🔴 {name} がルーム{entry['room']}から退室")
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(port=5000, debug=True)
