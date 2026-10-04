# 変更履歴

互換性のルールは [`versioning.md`](versioning.md) を参照。

## 1.0(草案)

- 最初の版
- Discovery(`/.well-known/mokumoco-world`)とスナップショット1本で取得する方式
- 空間種別 `room9`(もくもく会の9部屋)を定義
- 空間種別 `stream`(動画・音声の配信)を予約。接続側の再生対応は任意
- NPCの種類 `basic` / `clock` / `calendar` / `youtube` を定義
- 画像は接続側が中継、動画・音声ストリームだけはブラウザが直接参照する、という区別を定義
