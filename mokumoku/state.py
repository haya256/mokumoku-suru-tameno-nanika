import random
import threading

# 在室者・チャット・画像など、メモリ上だけに持つ状態(再起動で消える)。
# dict/listは中身を書き換えるだけで作り直さないので、他モジュールは名前ごとimportしてよい
messages = []
board = {}
# カスタムキャラ画像は board と同じライフサイクル(退室で破棄、再起動で消える)
custom_images = {}  # cid -> {"data": bytes, "v": int}
npc_images = {}  # npc board id -> {"data": bytes, "mime": str, "version": str} (YouTube NPCのサムネ)
# チャットに添付された画像。messagesと同じく無制限に増え続け、再起動で消える(既存の割り切りに合わせる)
message_images = {}  # image id -> bytes
# 他サーバーのチャット画像を中継した際のキャッシュ。peer_chara_imagesと同じ役割
peer_message_images = {}  # (peer_id, image_id) -> bytes
# エリアのマス絵(ピアの部屋画像やYouTubeのサムネ)。巡回スレッドと設置時の両方が書き込む
area_images = {}        # area_id -> {"data": bytes, "mime": str, "version": int|str|None, "at": float}
_img_seq = 0  # キャッシュバスター用の通し番号。退室しても巻き戻さない(再入室時のキャッシュ誤爆防止)
room_image_version = 0  # 部屋画像が変更されるたびに+1(クライアントが変化検知するためだけの値)
ROOM_COUNT = 9

# 空き部屋の確保〜board書き込みまでの間に別リクエストが割り込むと部屋番号が重複しうる
# (waitressはデフォルトでマルチスレッド)。join_boardとNPC追加の両方でこの区間を守る
_board_lock = threading.Lock()


def next_img_seq():
    global _img_seq
    _img_seq += 1
    return _img_seq

def bump_room_image_version():
    global room_image_version
    room_image_version += 1
    return room_image_version

# 空いている部屋番号を1つ選ぶ(無ければNone)。人間の入室(join_board)とNPCの入室で
# ロジックを共有することで、両者が同じ部屋番号を取り合わないことを構造的に保証する
def pick_free_room():
    used = {e["room"] for e in board.values()}
    free = [r for r in range(1, ROOM_COUNT + 1) if r not in used]
    return random.choice(free) if free else None
