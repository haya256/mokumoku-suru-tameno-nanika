"""エリア(ワールドマップのマス)と部屋NPCの種別の登録簿。

新しい種別を足すときは kinds/ にファイルを1つ作って Kind を継承し、下の一覧に加えるだけでよい。
「どこに置けるか」は各種別の places で決まる。
"""
from kinds.base import Kind, KindError, Prepared
from kinds.basic import BasicKind
from kinds.browser import BrowserKind
from kinds.calendar import CalendarKind
from kinds.clock import ClockKind
from kinds.peer import PeerKind
from kinds.youtube import YoutubeKind

KINDS = {k.key: k for k in (PeerKind(), YoutubeKind(), ClockKind(), CalendarKind(), BrowserKind(), BasicKind())}
AREA_KINDS = {key: k for key, k in KINDS.items() if "area" in k.places}
NPC_KINDS = {key: k for key, k in KINDS.items() if "npc" in k.places}

__all__ = ["KINDS", "AREA_KINDS", "NPC_KINDS", "Kind", "KindError", "Prepared"]
