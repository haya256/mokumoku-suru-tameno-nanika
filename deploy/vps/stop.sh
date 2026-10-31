#!/usr/bin/env bash
# deploy/vps/start.sh で起動した server.py と cloudflared を止める。
# PIDファイルにある、自分が起動したプロセスだけを止める(同じマシンにある別のトンネルなどは止めない)。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

stop_one() {
    local name="$1" pid_file="$2" marker="$3" pid
    echo "$name を止めています..."
    if [ ! -f "$pid_file" ]; then
        echo "  -> 動いていませんでした"
        return
    fi
    pid="$(cat "$pid_file")"
    if [ -z "$pid" ] || ! ps -p "$pid" -o command= 2>/dev/null | grep -qF -- "$marker"; then
        # 時間切れで止まった後など。PIDが別のプロセスに使い回されていても触らない
        echo "  -> 動いていませんでした"
        rm -f "$pid_file"
        return
    fi
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
        ps -p "$pid" >/dev/null 2>&1 || break
        sleep 0.25
    done
    if ps -p "$pid" >/dev/null 2>&1; then
        kill -9 "$pid" 2>/dev/null || true
        echo "  -> 強制的に止めました (PID: $pid)"
    else
        echo "  -> 止めました (PID: $pid)"
    fi
    rm -f "$pid_file"
}

# 先にトンネルを止めて、外から入れない状態にする
stop_one "cloudflared" "run/cloudflared.pid" "cloudflared"
stop_one "server.py" "run/server.pid" "server.py"

rm -f config/closing_at.txt
