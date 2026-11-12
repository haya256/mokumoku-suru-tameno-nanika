from flask import request

# リクエストのJSONを読むときの小さな道具。クライアントの入力は形を信用しない
# (JSONでない・オブジェクトでない・文字列のはずの値が数値や配列、など)。
# どれも500にせず「空」として扱い、あとは各処理の通常の検証(必須チェックや合言葉の判定)に任せる

# リクエスト本文をdictで返す。JSONとして読めない・オブジェクトでないときは空のdict
def json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}

# 文字列の項目を前後の空白を落として返す。無い・文字列でないときは空文字
def text_field(data, key):
    value = (data or {}).get(key)
    return value.strip() if isinstance(value, str) else ""
