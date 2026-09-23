"""もくもくルームのサーバー本体。server.py が Flask アプリを組み立ててここを読み込む。

    settings.py  config/settings.json の読み書き(毎回読み直すので再起動不要)
    state.py     在室者・チャット・画像などメモリ上だけの状態
    auth.py      合言葉・管理者合言葉の判定
    notify.py    システムメッセージとDiscord投稿
    areas.py     ワールドマップのエリア(設定ファイルに保存)
    peers.py     他のもくもくルーム(ピア)の巡回と中継キャッシュ
    kinds/       エリア/NPCの種別ごとの定義(新しい種別はここに1ファイル足す)
    routes/      URLごとの処理(room / world / npc / images)
    net.py, media.py  外部取得と画像検証の小さな道具
"""
