from mokumoku.kinds.base import Kind, KindError, Prepared, clean_name
from mokumoku.media import decode_chara_image


# 基本NPC: 名前・やること・画像(任意)を管理者がその都度自由入力する。部屋の中にだけ置ける
class BasicKind(Kind):
    key = "basic"
    emoji = "🤖"
    label = "NPC"
    places = ("npc",)

    def prepare(self, data):
        name = clean_name(data.get("name"))
        task = clean_name(data.get("task"), 80)
        if not name or not task:
            raise KindError("name and task required")
        raw = None
        if data.get("image"):
            raw = decode_chara_image(data.get("image"))
            if raw is None:
                raise KindError("invalid image")
        return Prepared(name=name, task=task, chara_image=raw)
