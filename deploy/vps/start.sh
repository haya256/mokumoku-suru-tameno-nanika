#!/usr/bin/env bash
# VPSなどで、server.py と cloudflared の Quick Tunnel をバックグラウンドで起動する。
#
#   deploy/vps/start.sh          # 4時間後に自動で止まる(既定)
#   deploy/vps/start.sh 2h       # 時間を指定(例: 90s / 30m / 1.5h / 1d / 90 は秒)
#   deploy/vps/start.sh none     # 時間制限なし(止めるのを忘れないこと)
#
# 止めるときは deploy/vps/stop.sh。
# 何もインストールしない(venv/ と cloudflared は用意済みの前提で、確かめるだけ)。
# DISCORD_WEBHOOK_URL や PORT などの環境変数は、そのまま server.py に引き継ぐ。
set -euo pipefail

# どこに clone しても動くよう、スクリプトの場所からリポジトリのルートを割り出す
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

RUN_DIR="run"
SERVER_PID_FILE="$RUN_DIR/server.pid"
TUNNEL_PID_FILE="$RUN_DIR/cloudflared.pid"
SERVER_LOG="$RUN_DIR/server.log"
TUNNEL_LOG="$RUN_DIR/cloudflared.log"
CLOSING_AT_FILE="config/closing_at.txt"
URL_WAIT_SECONDS=60

DURATION="${1:-4h}"
PORT="${PORT:-5000}"

die() {
    echo "エラー: $*" >&2
    exit 1
}

# PIDファイルのプロセスが、まだ動いていて、かつ自分が起動したもの(コマンドに目印を含む)か
is_running() {
    local pid_file="$1" marker="$2" pid
    [ -f "$pid_file" ] || return 1
    pid="$(cat "$pid_file")"
    [ -n "$pid" ] || return 1
    ps -p "$pid" -o command= 2>/dev/null | grep -qF -- "$marker"
}

# --- 引数と環境の確認 ---------------------------------------------------------

if [ "$#" -gt 1 ]; then
    die "引数は1つまでです(例: deploy/vps/start.sh 2h / deploy/vps/start.sh none)"
fi

[[ "$PORT" =~ ^[0-9]+$ ]] || die "PORT は数字で指定してください(今の値: $PORT)"

LIMIT_SECONDS=""
if [ "$DURATION" != "none" ]; then
    if ! [[ "$DURATION" =~ ^[0-9]+(\.[0-9]+)?[smhd]?$ ]]; then
        die "時間の書き方が違います: $DURATION
  例: 90s / 30m / 1.5h / 4h / 1d (単位なしは秒)。時間制限なしにするなら none"
    fi
    LIMIT_SECONDS="$(awk -v d="$DURATION" 'BEGIN {
        u = substr(d, length(d))
        m = (u == "d") ? 86400 : (u == "h") ? 3600 : (u == "m") ? 60 : 1
        printf "%d", (d + 0) * m
    }')"
    [ "$LIMIT_SECONDS" -ge 1 ] || die "時間は1秒以上にしてください: $DURATION"

    if command -v timeout >/dev/null 2>&1; then
        TIMEOUT_CMD="timeout"
    elif command -v gtimeout >/dev/null 2>&1; then
        TIMEOUT_CMD="gtimeout"
    else
        die "時間制限に使う timeout コマンドが見つかりません。
  macOS なら: brew install coreutils (gtimeout が入ります)
  どうしても時間制限なしで動かすなら: deploy/vps/start.sh none"
    fi
fi

if [ ! -x venv/bin/python ]; then
    die "venv/ が見つかりません。リポジトリのルートで次を実行してから、もう一度どうぞ:
  python3 -m venv venv
  venv/bin/pip install -r requirements.txt"
fi

if ! command -v cloudflared >/dev/null 2>&1; then
    die "cloudflared が見つかりません。README の「VPS + Cloudflare Tunnel」の節を見てインストールしてください"
fi

if is_running "$SERVER_PID_FILE" "server.py" || is_running "$TUNNEL_PID_FILE" "cloudflared"; then
    die "すでに動いています。止めるなら deploy/vps/stop.sh を実行してください"
fi

# --- 起動 ---------------------------------------------------------------------

mkdir -p "$RUN_DIR" config
# 前回のログは .1 に残す(1世代だけ)
for log in "$SERVER_LOG" "$TUNNEL_LOG"; do
    if [ -f "$log" ]; then mv -f "$log" "$log.1"; fi
done

if [ -n "$LIMIT_SECONDS" ]; then
    echo $(( $(date +%s) + LIMIT_SECONDS )) > "$CLOSING_AT_FILE"
    LIMIT=("$TIMEOUT_CMD" "$LIMIT_SECONDS")
else
    # 前に時間制限つきで起動したときの閉店時刻が残らないようにする
    rm -f "$CLOSING_AT_FILE"
    LIMIT=()
fi

export PORT
nohup ${LIMIT[@]+"${LIMIT[@]}"} venv/bin/python server.py > "$SERVER_LOG" 2>&1 &
echo $! > "$SERVER_PID_FILE"
echo "server.py を起動しました (PID: $!)"

# 待ち受けは 127.0.0.1 だけ。外からは Quick Tunnel 経由でしか届かない
nohup ${LIMIT[@]+"${LIMIT[@]}"} cloudflared tunnel --url "http://127.0.0.1:$PORT" > "$TUNNEL_LOG" 2>&1 &
echo $! > "$TUNNEL_PID_FILE"
echo "cloudflared を起動しました (PID: $!)"

# --- トンネルのURLを待つ ------------------------------------------------------

fail() {
    echo "エラー: $1" >&2
    echo "--- $2 の最後の20行 ---" >&2
    tail -n 20 "$2" >&2 || true
    echo "------------------------" >&2
    "$ROOT/deploy/vps/stop.sh" >/dev/null || true
    exit 1
}

echo "トンネルのURLを待っています(最大${URL_WAIT_SECONDS}秒)..."
url=""
for _ in $(seq 1 $(( URL_WAIT_SECONDS * 2 ))); do
    url="$(grep -oE 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -n 1 || true)"
    [ -n "$url" ] && break
    is_running "$SERVER_PID_FILE" "server.py" || fail "server.py が止まりました" "$SERVER_LOG"
    is_running "$TUNNEL_PID_FILE" "cloudflared" || fail "cloudflared が止まりました" "$TUNNEL_LOG"
    sleep 0.5
done
[ -n "$url" ] || fail "${URL_WAIT_SECONDS}秒待ってもURLが出ませんでした" "$TUNNEL_LOG"

echo
echo "参加者に伝えるURL: $url"
if [ -n "$LIMIT_SECONDS" ]; then
    end_at=$(( $(date +%s) + LIMIT_SECONDS ))
    end_clock="$(date -d "@$end_at" +%H:%M 2>/dev/null || date -r "$end_at" +%H:%M 2>/dev/null || true)"
    echo "$DURATION 後${end_clock:+(${end_clock}ごろ)}に自動で止まります。先に止めるなら deploy/vps/stop.sh"
else
    echo "時間制限なしで動いています。終わったら必ず deploy/vps/stop.sh で止めてください"
fi
if [ ! -s "config/合言葉.txt" ]; then
    echo "注意: 合言葉(config/合言葉.txt)が未設定です。URLを知っている人は誰でも書き込めます"
fi
echo "ログ: $SERVER_LOG / $TUNNEL_LOG"
