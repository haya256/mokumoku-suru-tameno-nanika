// サーバーの状態を2秒ごとに取りに行って画面全体を描き直す。最後に読み込まれる
const DISCORD_BADGES = {
  on:    { label: "Discord投稿: オン", title: "チャットと入退室はDiscordにも投稿されます" },
  off:   { label: "Discord投稿: オフ", title: "Discordには投稿されません(Webhook URL未設定)" },
  error: { label: "Discord投稿: エラー", title: "直近のDiscord投稿に失敗しました(Webhook URLが失効している可能性)" },
};

function renderStatus(status) {
  const badge = DISCORD_BADGES[status.discord];
  if (badge) {
    discordStatusEl.textContent = badge.label;
    discordStatusEl.title = badge.title;
    discordStatusEl.className = `header-badge ${status.discord}`;
  }
  renderClosingTime(status.closingAt);
  if (typeof status.roomImageVersion === "number") {
    scheduleRoomImageRefresh(status.roomImageVersion);
  }
  if (typeof status.title === "string" && status.title !== roomTitleEl.textContent) {
    roomTitleEl.textContent = status.title;
    document.title = status.title;
    renderWorld();
  }
  if (typeof status.favicon === "string" && status.favicon !== roomFavicon) {
    setFavicon(status.favicon);
  }
  if (typeof status.roomState === "string" && status.roomState !== roomState) {
    roomState = status.roomState;
    renderWorld();
  }
}

// 閉店時刻(起動シェルがtimeoutで自動終了させる時刻、UNIX秒)。無ければ(null)バッジを隠す。
// 今日でなければ(8hで日付をまたぐ場合など)日付も付ける
function renderClosingTime(closingAt) {
  closingTimeEl.hidden = typeof closingAt !== "number";
  if (closingTimeEl.hidden) return;
  const at = new Date(closingAt * 1000);
  const hm = `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}`;
  const sameDay = at.toDateString() === new Date().toDateString();
  closingTimeEl.textContent = `🕘 サーバー自動停止時刻 ${sameDay ? "" : `${at.getMonth() + 1}/${at.getDate()} `}${hm}`;
  closingTimeEl.title = "この時刻にサーバーが自動で終了します";
}

// 部屋画像が変わったことをpoll(2秒間隔)で検知したら、全員が同時に1〜2MBの画像を
// 再取得してアクセスが集中しないよう、0〜8秒のランダムな待ち時間を挟んでから反映する
// (poll間隔とジッターの合計で、最悪でも10秒程度以内には全員に反映される想定)
function scheduleRoomImageRefresh(version) {
  if (roomImageVersion === null) {
    // 初回pollでは「今表示中の画像がこのバージョン」という基準値を記録するだけ(再取得はしない)
    roomImageVersion = version;
    return;
  }
  if (version === roomImageVersion || version === pendingImageVersion) return;
  pendingImageVersion = version;
  const delay = Math.random() * 8000;
  setTimeout(() => {
    roomImageVersion = version;
    pendingImageVersion = null;
    selfRoomImageSrc = `/room-image.webp?v=${version}`;
    renderWorld();
  }, delay);
}

async function poll() {
  try {
    const [msgRes, boardRes, statusRes, worldRes] = await Promise.all([
      fetch("/messages"), fetch("/board"), fetch("/status"), fetch("/world"),
    ]);
    await checkAdmin();
    localMessages = await msgRes.json();
    const world = await worldRes.json();
    areas = Array.isArray(world.areas) ? world.areas : [];
    // 拡大表示中のエリアが片付けられたらマップ表示に戻す
    if (focusedKey && focusedKey !== "self" && !areas.some(a => a.id === focusedKey)) focusedKey = null;
    renderBoard(await boardRes.json());
    renderStatus(await statusRes.json());
    render(mergedMessages());
  } catch {}
}

renderWorld(); // 初回pollを待たずに自分のルームを出す
poll();
setInterval(poll, 2000);
