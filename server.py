import os
import urllib.request
import json as _json
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime

app = Flask(__name__)
messages = []
board = {}
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
        board[name] = {"name": name, "start": start, "end": end, "task": task}
        if is_new:
            until = f"〜{end}" if end else "〜"
            add_system_message(f"🟢 {name} がもくもく開始({start}{until}): {task}")

    return jsonify(msg), 201

@app.route("/board", methods=["GET"])
def get_board():
    return jsonify(list(board.values()))

@app.route("/board/end", methods=["POST"])
def end_board():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    if board.pop(name, None):
        add_system_message(f"🔴 {name} がもくもく終了")
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(port=5000, debug=True)
