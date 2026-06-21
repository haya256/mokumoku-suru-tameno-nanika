# もくもく会チャット

もくもく会（各自が黙々と作業する集まり）で使える軽量リアルタイムチャットアプリです。
参加者がコメントを投稿すると Discord にも通知されます。

## 機能

- 名前とコメントを入力して投稿
- 2秒ごとに自動更新（ポーリング）
- Discord Webhook 連携

## 使い方

### 必要なもの

- Python 3.x
- Flask

### セットアップ

```bash
pip install flask
```

### 起動

```bash
python server.py
```

ブラウザで http://localhost:5000 を開く。

### Discord 連携（任意）

環境変数に Webhook URL を設定する。

```bash
export DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
python server.py
```

## ライセンス

MIT
