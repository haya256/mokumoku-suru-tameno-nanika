# v1 以前の接続方式(参考)

v1 ができる前から動いている接続方式の記録です。**新しく作る実装はこれに対応する必要はありません**。
既存のもくもく会チャット(v1 未対応の版)とつなぎたいときだけ参照してください。

接続側は、Discovery(`/.well-known/mokumoco-world`)が取れない相手に対して、管理者の指定に応じて次のどちらかを試します。

## native 型(このリポジトリ系統の旧版。v0 扱い)

すべて認証なしの GET。ルートURLからの固定パスです。

| パス | 中身 |
|---|---|
| `/board` | 在室者の配列 `[{id, name, task, start, end, room, pose, imgv, npc?, kind?, videoId?, url?}]` |
| `/messages` | 発言の配列 `[{id?, uid?, name, text, time, ts?, image?, system?}]`(全件、古い順) |
| `/status` | `{roomImageVersion, roomState, title, favicon, closingAt, discord}` |
| `/room-image.webp` | 部屋の絵(WebP) |
| `/chara-custom/<id>.png` | キャラの絵(PNG)。`imgv` が 0 なら無い |
| `/message-image/<image>.webp` | チャット画像(WebP) |

v1 との主な違い:
- 4〜5回に分けて取る必要がある
- 版の情報が無いので、フィールドを変えると古い相手が壊れる
- `ts` が無い古い版がある(接続側は `time` の「HH:MM」を今日の時刻として補う)
- 画像の形式とURLの形が決め打ち

## fork 型(elm200 版: FastAPI + Redis + SSE)

| パス | 中身 |
|---|---|
| `GET /api/events` | SSE。接続直後に `data: {"board": [...], "messages": [...], "config": {"roomImage": "<ファイル名>", ...}}` を1回送る。接続側は最初の1イベントだけ読んで切断する |
| `/assets/<roomImage>` | 部屋の絵(PNG) |
| `/api/chara-custom?id=<id>` | キャラの絵(PNG) |

- 1回の取得ごとに相手の Redis コマンドを複数消費するため、巡回間隔は既定で60秒(設定で変更可)
- チャット画像は中継しない(メッセージの形が異なり画像URLを持たない)
