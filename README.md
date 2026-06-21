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

#### Webhook URL の取得手順

1. Discord で通知を送りたいチャンネルを右クリック → **「チャンネルの編集」**
2. **「連携サービス」** タブを開く
3. **「ウェブフック」** → **「新しいウェブフック」** をクリック
4. 名前を設定し、**「ウェブフック URL をコピー」** をクリック

> 開発者モードや Bot の登録は不要です。

#### 環境変数に設定して起動

```bash
export DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
python server.py
```

## ライセンス

MIT
