import random
import secrets

from mokumoku.settings import load_settings, update_settings

MAX_AREAS = 8            # 中央(自分)を除いた3×3マップの周囲8マス

# エリア一覧は毎回settings.jsonから読み直す。巡回スレッドもこれを使うので、管理者はサーバー稼働中に
# 設置・撤去でき再起動が要らない(合言葉や部屋画像が再起動不要なのと同じ流儀)。
# 旧バージョンが書いたworld.peersは、kind未指定=peerとして読めるのでそのまま受け入れる
# (書き込み時にworld.areasへ正規化される)
def load_areas():
    world = load_settings().get("world", {})
    raw = world.get("areas")
    if not isinstance(raw, list):
        raw = world.get("peers")
    if not isinstance(raw, list):
        return []
    areas = []
    for a in raw:
        if not isinstance(a, dict):
            continue
        # kindは手書きされうる(settings.jsonは手編集可とREADMEで案内している)。
        # 欠損はpeer扱いにし、未知の種別は落とさずそのまま通す(クライアント側が霧マスにする)
        areas.append({**a, "kind": a.get("kind") or "peer"})
    return areas

def find_area(area_id):
    return next((a for a in load_areas() if a.get("id") == area_id), None)

# ピア(他のもくもくルーム)だけを抜き出す。巡回スレッドとチャット/在室者のマージはこちらを使う
def load_peers():
    return [a for a in load_areas() if a.get("kind") == "peer"]

def find_peer(peer_id):
    return next((p for p in load_peers() if p.get("id") == peer_id), None)

# mutateの内側でエリア一覧を取り出す共通処理。旧world.peersが残っていればworld.areasへ移し替える
# (両方を残すとareasを消したときに古いpeersが亡霊のように復活するため、peersは必ず捨てる)
def _areas_for_write(settings):
    world = settings.setdefault("world", {})
    raw = world.get("areas")
    if not isinstance(raw, list):
        raw = world.get("peers") if isinstance(world.get("peers"), list) else []
    world.pop("peers", None)
    areas = [{**a, "kind": a.get("kind") or "peer"} for a in raw if isinstance(a, dict)]
    world["areas"] = areas
    return areas

# エリアをマップの空きマスに置く。kindは kinds/ の種別、fieldsは種別ごとの追加フィールド
# (peerならurl/type、youtubeならvideoId)
def add_area(kind, name, fields):
    def mutate(settings):
        areas = _areas_for_write(settings)
        if any(kind.is_duplicate(fields, a) for a in areas):
            return {"error": "duplicate"}
        # 上限は「8マス」。種別をまたいで1つの枠を取り合う
        if len(areas) >= MAX_AREAS:
            return {"error": "full"}
        # 空いているマスからランダムに選んで以降固定。設定に保存するので再起動しても動かない
        used = {a.get("slot") for a in areas}
        area = {"id": secrets.token_hex(4), "kind": kind.key, "name": name,
                "slot": random.choice([s for s in range(MAX_AREAS) if s not in used]), **fields}
        areas.append(area)
        return {"area": area}
    return update_settings(mutate)

def remove_area(area_id):
    def mutate(settings):
        areas = _areas_for_write(settings)
        settings["world"]["areas"] = [a for a in areas if a.get("id") != area_id]
        return next((a for a in areas if a.get("id") == area_id), None)
    return update_settings(mutate)

# 既存エリアの一部フィールドだけを書き換える(動画の差し替えなど)。id/kind/slotは動かさない
def update_area(area_id, fields):
    def mutate(settings):
        areas = _areas_for_write(settings)
        area = next((a for a in areas if a.get("id") == area_id), None)
        if area is None:
            return None
        area.update(fields)
        return area
    return update_settings(mutate)
