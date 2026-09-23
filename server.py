import mimetypes
import os
import threading
import time

from flask import Flask, send_from_directory

from mokumoku.peers import peer_poll_loop
from mokumoku.routes import images, npc, room, world

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

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

# waitress以外から起動された場合も巡回が回るよう、__main__ではなくモジュール読み込み時に開始する
threading.Thread(target=peer_poll_loop, daemon=True).start()

if __name__ == "__main__":
    from waitress import serve
    port = int(os.environ.get("PORT", "5000"))
    print(f"もくもくサーバー起動: http://127.0.0.1:{port} (停止は Ctrl+C)", flush=True)
    serve(app, host="127.0.0.1", port=port)
