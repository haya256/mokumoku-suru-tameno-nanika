import base64
import binascii

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
WEBP_MAGIC_HEAD = b"RIFF"
WEBP_MAGIC_TAIL = b"WEBP"
JPEG_MAGIC = b"\xff\xd8"
MAX_IMAGE_B64 = 700_000
MAX_CHAT_IMAGE_B64 = 4_000_000  # チャット画像はアバターより大きめの表示サイズを許容する

def is_webp(data):
    return data[:4] == WEBP_MAGIC_HEAD and data[8:12] == WEBP_MAGIC_TAIL

# クライアントがcanvasで縮小・PNG化したデータURLを検証してPNGバイト列を返す。不正ならNone
def decode_chara_image(image):
    prefix = "data:image/png;base64,"
    if not isinstance(image, str) or not image.startswith(prefix) or len(image) > MAX_IMAGE_B64:
        return None
    try:
        raw = base64.b64decode(image[len(prefix):], validate=True)
    except (ValueError, binascii.Error):
        return None
    if not raw.startswith(PNG_MAGIC):
        return None
    return raw

# クライアントがcanvasで縮小・WebP化したデータURLを検証してWebPバイト列を返す。不正ならNone
def decode_chat_image(image):
    prefix = "data:image/webp;base64,"
    if not isinstance(image, str) or not image.startswith(prefix) or len(image) > MAX_CHAT_IMAGE_B64:
        return None
    try:
        raw = base64.b64decode(image[len(prefix):], validate=True)
    except (ValueError, binascii.Error):
        return None
    if not is_webp(raw):
        return None
    return raw
