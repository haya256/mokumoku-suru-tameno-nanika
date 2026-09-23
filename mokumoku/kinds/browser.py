import urllib.error
import urllib.parse
import urllib.request

from mokumoku import net
from mokumoku.kinds.base import Kind, KindError, Prepared, clean_name


# ブラウザ用。peerと違い任意のページを指すのでパス・クエリ・フラグメントを許可する
def normalize_iframe_url(url):
    url = (url or "").strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return url

# 埋め込み可否のベストエフォート判定。X-Frame-Options/CSPで「明らかに拒否」と
# 分かる場合だけFalseにし、それ以外(判定不能・通信失敗・ドメイン限定のframe-ancestors等)はTrue側に
# 倒す。誤って「埋め込めない」と警告して置くのを迷わせるより、置けた後に気づく方がましという判断
def check_iframe_embeddable(url):
    req = urllib.request.Request(url, headers={"User-Agent": net.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=net.TIMEOUT) as res:
            headers = res.headers
    except urllib.error.HTTPError as e:
        headers = e.headers
    except Exception:
        return True
    if (headers.get("X-Frame-Options") or "").strip().lower() in ("deny", "sameorigin"):
        return False
    for directive in (headers.get("Content-Security-Policy") or "").split(";"):
        parts = directive.strip().split()
        if parts and parts[0].lower() == "frame-ancestors":
            values = [v.lower() for v in parts[1:]]
            if not values or values in (["'none'"], ["'self'"]):
                return False
    return True


# ブラウザ: サーバーが名前とURLを持つが、ページの中身には一切関与しない
# (iframeは参加者のブラウザが直接読む)。peerと違いURLをそのまま/worldに返す
class BrowserKind(Kind):
    key = "browser"
    emoji = "🌐"
    label = "ブラウザ"
    places = ("area",)

    def prepare(self, data):
        url = normalize_iframe_url(data.get("url"))
        if not url:
            raise KindError("invalid url")
        name = clean_name(data.get("name")) or urllib.parse.urlparse(url).netloc
        return Prepared(name=name, fields={"url": url},
                        response={"embeddable": check_iframe_embeddable(url)})

    def display_name(self, area):
        return area.get("name") or urllib.parse.urlparse(area.get("url") or "").netloc

    def public_fields(self, area):
        return {"url": area.get("url")}
