import hmac

from flask import jsonify

from mokumoku.settings import DEFAULT_ADMIN_PASSPHRASE_FILE, load_settings, passphrase_file, read_secret_file
from mokumoku.state import board, seat_tokens

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
#   none      … 合言葉なしで入室できる
#   very_easy … 閲覧は自由。新規入室には部屋共通の合言葉が必要。
#               ただし合言葉ファイルが未設置(または空)の間は認証なしで通す
# 管理者合言葉(config/管理者合言葉.txt)を入力した場合も、部屋共通の合言葉の代わりとして通す。
# これにより「合言葉欄に管理者合言葉を入れる」だけで通常の書き込み権限+管理者権限を両方得られる。
# 入室後の発言・編集・退室はどちらのモードでも入室証(seat_entry)で本人確認する
def check_passphrase(data):
    security = load_settings().get("security", {})
    if security.get("mode", "very_easy") != "very_easy":
        return None
    expected = read_secret_file(passphrase_file())
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


# 入室証の照合。idと入室証(seat)が一致すればboardのエントリを、しなければNoneを返す。
# 合言葉は新規入室のときだけ確認し、入室後は入室証で本人確認する。
# そのため管理者が合言葉を変えても、入室中の人は聞き直されずに続けられる
def seat_entry(data):
    cid = ((data or {}).get("id") or "").strip()
    supplied = ((data or {}).get("seat") or "").strip()
    expected = seat_tokens.get(cid)
    if not expected or not hmac.compare_digest(supplied.encode(), expected.encode()):
        return None
    return board.get(cid)
