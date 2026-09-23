from kinds.base import Kind


# カレンダー: 時計と同じくサーバーが持つのは名前だけ。日付は見ている人のブラウザの
# ローカル日付をそのまま描く(サーバーの日付でもタイムゾーン指定でもない)ので、
# 巡回もキャッシュも中継する絵も一切要らない
class CalendarKind(Kind):
    key = "calendar"
    emoji = "📅"
    label = "カレンダー"
    default_name = "カレンダー"
    places = ("area", "npc")
