import json as _json
import os
import re
import tempfile
import threading

SETTINGS_FILE = "config/settings.json"
DEFAULT_PASSPHRASE_FILE = "config/合言葉.txt"
DEFAULT_ADMIN_PASSPHRASE_FILE = "config/管理者合言葉.txt"
ROOM_IMAGE_DIR = "assets"
ROOM_IMAGE_PATTERN = re.compile(r"^room-image-\d+\.webp$")
DEFAULT_ROOM_TITLE = "もくもく会"
ROOM_TITLE_MAX_LEN = 40
_settings_write_lock = threading.Lock()

# 設定は毎回読む(サーバー再起動なしでモード切替できるようにするため)
def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return _json.load(f)
    except (OSError, ValueError) as e:
        print(f"[settings] {SETTINGS_FILE} を読めないためデフォルト(mode=very_easy)で動作: {e}")
        return {}

# settings.jsonへの書き込みは他キー(security/deploy等)を保持したまま部分更新する。
# tmpファイル+os.replaceでアトミックに置換し、書き込み途中でプロセスが落ちても壊れたJSONを残さない
def save_settings(settings):
    directory = os.path.dirname(SETTINGS_FILE) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".settings-", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            _json.dump(settings, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, SETTINGS_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

# 読み→変更→書きをロックの内側でまとめて行う。mutateは settings dict を直接書き換える関数で、
# その戻り値をそのまま呼び出し元に返す(追加したピアなど、書き込み結果を知りたい場合のため)
def update_settings(mutate):
    with _settings_write_lock:
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                settings = _json.load(f)
        except (OSError, ValueError):
            settings = {}
        result = mutate(settings)
        save_settings(settings)
        return result

# appearance.room_imageだけを部分更新する。filenameはlist_room_images()で検証済みの前提
def set_room_image_setting(filename):
    def mutate(settings):
        settings.setdefault("appearance", {})["room_image"] = f"{ROOM_IMAGE_DIR}/{filename}"
    update_settings(mutate)

# appearance.room_stateだけを部分更新する。stateはROOM_STATESで検証済みの前提
def set_room_state_setting(state):
    def mutate(settings):
        settings.setdefault("appearance", {})["room_state"] = state
    update_settings(mutate)

# appearance.titleだけを部分更新する。titleは空でなく長さ上限内であることを検証済みの前提
def set_room_title_setting(title):
    def mutate(settings):
        settings.setdefault("appearance", {})["title"] = title
    update_settings(mutate)

# 画面上部・ブラウザのタブに出すタイトル。未設定/空なら既定の「もくもく会」
def room_title():
    title = load_settings().get("appearance", {}).get("title")
    return title.strip() if isinstance(title, str) and title.strip() else DEFAULT_ROOM_TITLE

# ファイルの中身を返す。未設置/空ならNone(hmac.compare_digestに渡す前提なので空文字とは区別する)
def read_secret_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            value = f.read().strip()
    except OSError:
        return None
    return value or None

# 部屋画像として選択可能なファイルの一覧。命名規則を正規表現で完全一致させることで、
# 以降の処理はこの戻り値に含まれるかどうかだけで判定でき、パストラバーサルの余地がない
def list_room_images():
    try:
        names = os.listdir(ROOM_IMAGE_DIR)
    except OSError:
        return []
    return sorted(n for n in names if ROOM_IMAGE_PATTERN.fullmatch(n))
