// 動画の再生管理。エリアのYouTubeマスと部屋セル内のYouTube NPCの両方を受け持つ
// 再生中の動画は同時に1つだけにする(エリアのタイル・部屋セル内のYouTube NPC・
// ステータスウィンドウの再生ステージすべてを合わせて)。複数が同時に鳴ると音が混ざるうえ、
// 拡大表示中は他のマスが隠れるので、どれを止めればいいのか分からなくなる
function stopAllPlayback() {
  tiles.forEach(stopTilePlayback);
  tiles.forEach(stopRoomNpcPlayback);
}

function startTilePlayback(tile) {
  if (!tile.videoId) return;
  stopAllPlayback();
  tile.playing = true;
  tile.player.hidden = false;
  tile.player.replaceChildren(buildYouTubeEmbed(tile.videoId, { autoplay: true }));
  // 狭い画面ではマスが130px前後しかなく、YouTubeのコントロールがほぼ隠れてしまうので
  // 再生と同時に拡大する
  if (window.matchMedia("(max-width: 800px)").matches && focusedKey !== tile.key) {
    focusedKey = tile.key;
  }
  renderWorld();
}

// iframeは隠すだけでは音が止まらないので必ず取り除く。DOMから外して作り直す前提なので、
// 逆に「再生したまま別の場所へ移す」ことはできない(移すとリロードされて頭から再生になる)
function stopTilePlayback(tile) {
  if (!tile.playing) return;
  tile.playing = false;
  tile.player.hidden = true;
  tile.player.replaceChildren();
}

// 部屋セル内のYouTube NPC再生を開始する。▶ボタンは拡大時にしか表示されない
// (=ステータスウィンドウのオーバーレイがマップ全体を覆っている間は押せない)ので、
// モーダル側の再生を止める必要はここには無い(モーダル側のstopAllPlayback呼び出しでカバー済み)
function startRoomNpcPlayback(tile, o) {
  stopAllPlayback();
  tile.playingNpcId = o.id;
  tile.playingNpcName = o.name;
  renderWorld();
}

// stopTilePlaybackと同じ理由でiframeは即座に取り除く。renderWorld()は呼び出し元に任せる
// (stopAllPlaybackから複数回呼ばれても再描画は1回で済むように)
function stopRoomNpcPlayback(tile) {
  if (!tile.playingNpcId) return;
  tile.playingNpcId = null;
  tile.playingNpcName = null;
  const cell = tile.cells.find(c => c.querySelector(".npc-youtube-playing"));
  if (cell) cell.innerHTML = "";
}

// 拡大表示中は再生中のマスがCSSで隠れる(音は鳴り続ける)ので、どこを見ていても
// 止められる手綱をマップ上に常設する
function renderNowPlaying() {
  const playingArea = tiles.find(t => t.playing);
  const playingRoom = tiles.find(t => t.playingNpcId);
  const playing = playingArea || playingRoom;
  nowPlayingBar.hidden = !playing;
  if (!playing) return;
  nowPlayingLabel.textContent = `▶ ${playingArea ? (playingArea.areaName || "YouTube") : playingRoom.playingNpcName}`;
  nowPlayingGoBtn.hidden = focusedKey === playing.key;
  nowPlayingBar.dataset.key = playing.key;
}

nowPlayingStopBtn.addEventListener("click", () => {
  stopAllPlayback();
  renderWorld();
});

nowPlayingGoBtn.addEventListener("click", () => {
  const playing = tiles.find(t => t.playing) || tiles.find(t => t.playingNpcId);
  if (playing) { focusedKey = playing.key; renderWorld(); }
});
