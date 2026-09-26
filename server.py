import html
import mimetypes
import os
import threading
import time

from flask import Flask, request

from mokumoku.peers import peer_poll_loop
from mokumoku.routes import images, npc, room, world
from mokumoku.settings import DEFAULT_ROOM_TITLE, room_title

# サーバーのOSタイムゾーン(EC2は既定でUTC)に関わらず、入退室記録をJST(クライアント側の時刻)と揃える
os.environ["TZ"] = "Asia/Tokyo"
time.tzset()

# Python標準のmimetypesは.webpを認識しない(3.12時点)ため、Content-Typeが正しく付くよう明示登録する。
# 未登録のままだとブラウザがimgタグで表示できない形で配信されてしまう
mimetypes.add_type("image/webp", ".webp")

# 処理の中身は mokumoku/ にある。ここはFlaskアプリの組み立てと起動だけを受け持つ
# (config/ と assets/ と index.html は、起動したディレクトリからの相対パスで読む)
app = Flask(__name__)
# チャット画像(WebP)をJSONボディに積むため、アバターのみだった頃の2MBから拡大
app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024
for module in (room, world, npc, images):
    app.register_blueprint(module.bp)

# ブラウザが2秒ごとに取り直すpoll先。本体からETagを作り、前回と変わっていなければ
# 304(本体なし)だけを返す。ブラウザは手元の前回分をそのまま使うので、クライアント側の変更は要らない。
# 問い合わせ自体は残る(サーバーに聞かないと変化の有無が分からないため)
POLL_PATHS = {"/messages", "/board", "/status", "/world"}

@app.after_request
def skip_unchanged_poll(response):
    if request.method == "GET" and request.path in POLL_PATHS and response.status_code == 200:
        response.headers["Cache-Control"] = "no-cache"
        response.add_etag()
        response.make_conditional(request)
    return response

@app.route("/")
def index():
    # 表示直後から設定済みのタイトルが出るよう、既定タイトルの箇所を差し替えて返す(以後の変更はpollで追随)
    with open("index.html", encoding="utf-8") as f:
        page = f.read()
    title = html.escape(room_title())
    for tag in ("<title>{}</title>", '<span id="roomTitle">{}</span>'):
        page = page.replace(tag.format(DEFAULT_ROOM_TITLE), tag.format(title))
    return page

# waitress以外から起動された場合も巡回が回るよう、__main__ではなくモジュール読み込み時に開始する
threading.Thread(target=peer_poll_loop, daemon=True).start()

if __name__ == "__main__":
    from waitress import serve
    port = int(os.environ.get("PORT", "5000"))
    print(f"もくもくサーバー起動: http://127.0.0.1:{port} (停止は Ctrl+C)", flush=True)
    serve(app, host="127.0.0.1", port=port)
