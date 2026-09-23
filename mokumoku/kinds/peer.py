import urllib.parse

from mokumoku.kinds.base import Kind, KindError, Prepared, clean_name

PEER_TYPES = ("native", "fork")  # native: このリポジトリ系統(Flask+ポーリング) / fork: elm200版(FastAPI+Redis+SSE)

# 受け付けるのはホストまでのURLだけ。パス付きは中継先URLの組み立てが壊れるので弾く。
# schemeを絞るのは、取得した中身を参加者に中継する以上file:などを踏ませないため
def normalize_peer_url(url):
    url = (url or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    if parsed.path or parsed.query or parsed.fragment:
        return None
    return url


# ピア: 他のもくもくルーム。相手の在室者・チャット・部屋画像は巡回スレッド(peers.py)が取りに行く。
# 未認証で開ける/worldには相手のURLを出さない(表示名とnetlocまで)
class PeerKind(Kind):
    key = "peer"
    emoji = "🌏"
    label = "もくもくルーム"
    places = ("area",)

    def prepare(self, data):
        url = normalize_peer_url(data.get("url"))
        if not url:
            raise KindError("invalid url")
        name = clean_name(data.get("name")) or urllib.parse.urlparse(url).netloc
        peer_type = data.get("type") if data.get("type") in PEER_TYPES else "native"
        return Prepared(name=name, fields={"url": url, "type": peer_type})

    def display_name(self, area):
        return area.get("name") or urllib.parse.urlparse(area.get("url", "")).netloc

    # 同じ相手ルームを二重に登録させない
    def is_duplicate(self, fields, other):
        return other.get("kind") == self.key and other.get("url") == fields.get("url")

    def placed_text(self, admin, name):
        return f"{self.emoji} {admin}が「{name}」とつながりました"

    def removed_text(self, admin, name):
        return f"{self.emoji} {admin}が「{name}」との接続を解除しました"
