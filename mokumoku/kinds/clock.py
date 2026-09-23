from mokumoku.kinds.base import Kind


# 時計: サーバーが持つのは名前だけ。時刻は見ている人のブラウザのローカル時刻を
# クライアントがそのまま描く(サーバーの時刻でもタイムゾーン指定でもない)ので、
# 巡回もキャッシュも中継する絵も一切要らない
class ClockKind(Kind):
    key = "clock"
    emoji = "🕐"
    label = "時計"
    default_name = "時計"
    places = ("area", "npc")
