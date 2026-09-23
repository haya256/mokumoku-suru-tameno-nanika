from dataclasses import dataclass, field


class KindError(Exception):
    """管理者の入力が不正なときに投げる。routes/ 側で {"error": code} の400応答に変換される"""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass
class Prepared:
    """prepare()の結果。エリアとしてもNPCとしても同じ形で使う"""
    name: str
    fields: dict = field(default_factory=dict)  # 設定(エリア)やboard(NPC)にそのまま保存する種別固有の値
    task: str = ""                              # NPCの「やること」欄
    chara_image: bytes | None = None            # NPCのカスタムキャラ画像(PNG)
    image: dict | None = None                   # 自サーバーが中継する絵 {"data", "mime", "version"}
    response: dict = field(default_factory=dict)  # 追加・差し替えの応答に添える値(埋め込み可否など)


# 名前はシステムメッセージとDiscordにも載るので、改行を潰して長さを切る
def clean_name(value, limit=40):
    return " ".join((value or "").split())[:limit]


class Kind:
    """種別の共通の形。新しい種別はこれを継承して kinds/__init__.py に登録するだけで、
    /admin/area・/admin/npc・/world・巡回スレッドのすべてに反映される"""
    key = ""
    emoji = ""
    label = ""            # システムメッセージでの呼び名(例: 時計)
    default_name = ""
    places = ()           # "area"(ワールドマップのマス) / "npc"(部屋の中)
    updatable = False     # 設置後に中身を差し替えられるか

    # 入力を検証して Prepared を返す。不正なら KindError を投げる
    def prepare(self, data):
        return Prepared(name=clean_name(data.get("name")) or self.default_name)

    # /world で返す名前。手編集で名前が空になっていても何か出るようにする
    def display_name(self, area):
        return area.get("name") or self.default_name

    # /world に載せる種別固有の値(未認証で見えるので、出してよいものだけ)
    def public_fields(self, area):
        return {}

    # 巡回スレッドから呼ばれる。中継する絵を取り直す必要があれば {"data", "mime", "version"} を返す
    def refresh_image(self, area, cached):
        return None

    # 同じものを二重に置かせないための判定
    def is_duplicate(self, fields, other):
        return False

    def placed_text(self, admin, name):
        return f"{self.emoji} {admin}が{self.label}「{name}」を置きました"

    def removed_text(self, admin, name):
        return f"{self.emoji} {admin}が{self.label}「{name}」を片付けました"

    def updated_text(self, admin, name):
        return f"{self.emoji} {admin}が{self.label}を「{name}」に変えました"
