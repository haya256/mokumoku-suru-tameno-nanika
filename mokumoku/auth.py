import hmac

from flask import jsonify

from mokumoku.settings import DEFAULT_ADMIN_PASSPHRASE_FILE, DEFAULT_PASSPHRASE_FILE, load_settings, read_secret_file
from mokumoku.state import board

def is_admin_passphrase(supplied):
    security = load_settings().get("security", {})
    path = security.get("admin_passphrase_file", DEFAULT_ADMIN_PASSPHRASE_FILE)
    expected = read_secret_file(path)
    if expected is None:
        return False
    return hmac.compare_digest((supplied or "").strip().encode(), expected.encode())

# 管理者操作のログに載せる実行者名。クライアントが送る actorId(自分のクライアントID)から入室中の名前を引く。
# 見る専(未入室)などで名前が引けないときは「管理者」だけにする
def admin_label(data):
    entry = board.get(((data or {}).get("actorId") or "").strip())
    name = (entry or {}).get("name")
    return f"{name}（管理者）" if name else "管理者"

# セキュリティモード(デフォルト: very_easy):
#   none      … 認証なし(閲覧・書き込みとも自由)
#   very_easy … 閲覧は自由。書き込み系(投稿/入室/退室)は部屋共通の合言葉が必要。
#               ただし合言葉ファイルが未設置(または空)の間は認証なしで通す
# 管理者合言葉(config/管理者合言葉.txt)を入力した場合も、部屋共通の合言葉の代わりとして通す。
# これにより「合言葉欄に管理者合言葉を入れる」だけで通常の書き込み権限+管理者権限を両方得られる。
def check_passphrase(data):
    security = load_settings().get("security", {})
    if security.get("mode", "very_easy") != "very_easy":
        return None
    path = security.get("passphrase_file", DEFAULT_PASSPHRASE_FILE)
    expected = read_secret_file(path)
    if expected is None:
        return None
    supplied = ((data or {}).get("passphrase") or "").strip()
    if hmac.compare_digest(supplied.encode(), expected.encode()):
        return None
    if is_admin_passphrase(supplied):
        return None
    return jsonify({"error": "wrong passphrase", "authRequired": True}), 401


# 管理者専用エンドポイントの入口。合言葉が違えば403応答を、正しければNoneを返す
def require_admin(data):
    supplied = ((data or {}).get("passphrase") or "").strip()
    if not is_admin_passphrase(supplied):
        return jsonify({"error": "admin required"}), 403
    return None
