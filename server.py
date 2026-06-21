import os
import urllib.request
import json as _json
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime

app = Flask(__name__)
messages = []
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

def post_to_discord(name, text):
    if not DISCORD_WEBHOOK_URL:
        return
    payload = _json.dumps({"content": f"**{name}**: {text}"}).encode()
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
    post_to_discord(name, text)
    return jsonify(msg), 201

if __name__ == "__main__":
    app.run(port=5000, debug=True)
