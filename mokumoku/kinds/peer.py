import urllib.parse

from mokumoku.kinds.base import Kind, KindError, Prepared, clean_name

# auto: 登録時にワールド接続プロトコルのDiscoveryを試し、話せればv1、だめならnative /
# v1: ワールド接続プロトコル v1(docs/world-protocol/) / native: このリポジトリ系統の旧方式(Flask+ポーリング) /
# fork: elm200版(FastAPI+Redis+SSE)
PEER_TYPES = ("auto", "v1", "native", "fork")

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
        peer_type = data.get("type") if data.get("type") in PEER_TYPES else "auto"
        fields = {"url": url, "type": peer_type}
        found_name = ""
        if peer_type in ("auto", "v1"):
            # kinds/ の読み込み中に protocol_v1 → kinds.youtube と循環しないよう、使うときに読み込む
            from mokumoku import protocol_v1
            found = protocol_v1.discover(url)
            if found:
                fields = {"url": url, "type": "v1", "snapshot": found["snapshot"], "minPoll": found["minPoll"]}
                found_name = clean_name(found["name"])
            elif peer_type == "v1":
                raise KindError("protocol not found")
            else:
                fields["type"] = "native"
        name = clean_name(data.get("name")) or found_name or urllib.parse.urlparse(url).netloc
        return Prepared(name=name, fields=fields)

    def display_name(self, area):
        return area.get("name") or urllib.parse.urlparse(area.get("url", "")).netloc

    # 同じ相手ルームを二重に登録させない
    def is_duplicate(self, fields, other):
        return other.get("kind") == self.key and other.get("url") == fields.get("url")

    def placed_text(self, admin, name):
        return f"{self.emoji} {admin}が「{name}」とつながりました"

    def removed_text(self, admin, name):
        return f"{self.emoji} {admin}が「{name}」との接続を解除しました"
