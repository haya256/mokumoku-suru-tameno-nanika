import re
import urllib.parse

import net
from kinds.base import Kind, KindError, Prepared, clean_name
from media import JPEG_MAGIC

# 動画IDは必ずASCII限定で検証する。Pythonの \w はUnicodeマッチなので全角文字が通ってしまう
YOUTUBE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{11}")
YOUTUBE_THUMB_MAX = 1_000_000  # 実測で最大のmaxresdefaultでも100KB弱。部屋画像の6MB枠を使い回す必要はない
# hqdefault(480x360)は必ずあるが4:3で上下に黒帯が焼き込まれているため使わない。16:9のものを
# 大きい順に試し、maxresdefault(1280x720)が無ければmqdefault(320x180)に落とす
YOUTUBE_THUMB_NAMES = ("maxresdefault.jpg", "mqdefault.jpg")

# YouTubeの各種URL形式(watch?v=, youtu.be/, shorts/, embed/)、または生の動画IDから11文字のIDを取り出す。
# クライアントのextractYouTubeId()と同じ判定をサーバー側でもやる(クライアントの検証は当てにしない)
def extract_youtube_id(value):
    value = (value or "").strip()
    if not value:
        return None
    ok = lambda s: s if YOUTUBE_ID_PATTERN.fullmatch(s or "") else None
    if "/" not in value and "?" not in value:
        return ok(value)  # 生のIDを直接貼られた場合
    try:
        u = urllib.parse.urlparse(value if "//" in value else f"https://{value}")
    except ValueError:
        return None
    host = (u.hostname or "").removeprefix("www.").removeprefix("m.")
    if host == "youtu.be":
        return ok(u.path.lstrip("/").split("/")[0])
    if host in ("youtube.com", "youtube-nocookie.com"):
        if u.path == "/watch":
            return ok(urllib.parse.parse_qs(u.query).get("v", [""])[0])
        m = re.fullmatch(r"/(?:shorts|embed|live)/([^/]+)", u.path)
        if m:
            return ok(m.group(1))
    return None

# サムネイルは自サーバーが取得して参加者に中継する(部屋画像と同じ流儀)。動画IDは検証済みなので
# パスに記号が混ざることはなく、組み立て先はi.ytimg.comの決め打ちパスに固定される
def fetch_youtube_thumbnail(video_id):
    last_error = None
    for name in YOUTUBE_THUMB_NAMES:
        try:
            data = net.fetch_bytes(f"https://i.ytimg.com/vi/{video_id}/{name}", YOUTUBE_THUMB_MAX)
        except Exception as e:
            last_error = e
            continue
        # 中継するバイト列が本当に画像かは相手任せにせずこちらでも確かめる
        if not data.startswith(JPEG_MAGIC):
            last_error = ValueError("not a jpeg image")
            continue
        return data
    raise last_error or ValueError("no thumbnail available")

# 動画タイトルをoEmbedから取る(APIキー不要)。表示名が未指定のときのフォールバックに使うだけなので、
# 取れなくても機能は成立する。埋め込み禁止・非公開の動画はここが401/404になるので事前警告にも使える
def fetch_youtube_title(video_id):
    watch_url = urllib.parse.quote(f"https://www.youtube.com/watch?v={video_id}", safe="")
    info = net.fetch_json(f"https://www.youtube.com/oembed?url={watch_url}&format=json")
    # 切った拍子に開き括弧だけが残ると尻切れ感が強いので、末尾の区切り文字はまとめて落とす
    return clean_name(str(info.get("title") or "")).rstrip(" -–—([{「『【（").strip() or None

def thumbnail_image(video_id, data):
    # versionに動画IDを入れておくと、差し替え時だけ取り直せる
    return {"data": data, "mime": "image/jpeg", "version": video_id}


# YouTube: 管理者が指定した動画1本を持つ。エリア(マップのマス)にも部屋NPCにもなれる。
# サムネイルは自サーバーが中継し、参加者が再生ボタンを押すまでブラウザはYouTubeと通信しない
class YoutubeKind(Kind):
    key = "youtube"
    emoji = "📺"
    label = "YouTubeルーム"
    default_name = "YouTube"
    places = ("area", "npc")
    updatable = True

    # サムネとタイトルはここで同期的に取りに行く。巡回スレッド任せにすると、置いた直後の数秒間
    # マスが空白になるうえ、動画を差し替えたときに新しいキャッシュバスターURLで古いサムネが返り、
    # Cache-Controlの24時間がブラウザに焼き付いてしまう
    def prepare(self, data):
        video_id = extract_youtube_id(data.get("url") or data.get("videoId"))
        if not video_id:
            raise KindError("invalid video")
        # 削除済み・限定公開などサムネイルすら取れない動画は、置いても意味がないのでここで弾く
        try:
            thumbnail = fetch_youtube_thumbnail(video_id)
        except Exception as e:
            print(f"[areas] サムネイル取得に失敗: {e}")
            raise KindError("video unavailable")
        # oEmbedは埋め込みを禁止している動画に401を返すので、タイトルが要らない場合でも必ず叩いて
        # 「置けたのに再生できない」を事前に警告する。ただし通信の一時的な失敗と区別が付かないため、
        # 設置自体は止めない(サムネが取れている以上、動画そのものは存在している)
        title = None
        try:
            title = fetch_youtube_title(video_id)
        except Exception as e:
            print(f"[areas] タイトル取得に失敗: {e}")
        name = clean_name(data.get("name")) or title or self.default_name
        return Prepared(name=name, fields={"videoId": video_id},
                        image=thumbnail_image(video_id, thumbnail),
                        response={"embeddable": title is not None})

    def public_fields(self, area):
        return {"videoId": area.get("videoId")}

    # 設置・差し替え時に同期取得しているので、ここで取り直すのは
    # 「サーバーを再起動してインメモリのキャッシュが消えた」場合だけ。
    # ピアの部屋画像と違い相手が黙って中身を差し替えることはないので、期限切れ再取得はしない
    def refresh_image(self, area, cached):
        video_id = area.get("videoId")
        # settings.jsonを手編集された場合に備えて、取りに行く前にIDの形を確かめる
        if not YOUTUBE_ID_PATTERN.fullmatch(video_id or ""):
            raise ValueError("invalid video id")
        if cached and cached["version"] == video_id:
            return None
        return thumbnail_image(video_id, fetch_youtube_thumbnail(video_id))

    def updated_text(self, admin, name):
        return f"{self.emoji} {admin}がYouTubeルームの動画を「{name}」に変えました"
