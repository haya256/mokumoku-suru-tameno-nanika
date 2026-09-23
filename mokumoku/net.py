import json as _json
import urllib.request

# 外部サーバー(ピア・YouTube等)から取ってくるときの共通設定。
# 呼び出し側は `net.fetch_bytes(...)` の形で参照すること(テストがこのモジュールの関数を差し替えるため、
# `from net import fetch_bytes` で名前を取り込むと差し替えが効かなくなる)
USER_AGENT = "mokumoku-bot/1.0"
TIMEOUT = 5
JSON_MAX = 1_000_000

# 中継先は呼び出し側の決め打ちパスのみ。任意パスのプロキシにはしない
def fetch_bytes(url, limit):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        data = res.read(limit + 1)
    if len(data) > limit:
        raise ValueError("response too large")
    return data

def fetch_json(url):
    return _json.loads(fetch_bytes(url, JSON_MAX).decode("utf-8"))
