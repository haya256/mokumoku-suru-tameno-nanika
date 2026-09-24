// 管理者が置いた動画1本。エリア(マップのマス)にも部屋NPCにもなれる。
// どちらも「押すまで通信・再生しない」原則で、▶が押された時点で初めてiframeを差し込む
// (置いただけでiframeを作ると、マップを開いただけでYouTubeとの通信と再生が始まってしまう)。
// 再生中の管理(同時に鳴らせるのは1つだけ、など)は playback.js が受け持つ
const VIDEO_EMBED_WARNING = "この動画は外部サイトへの埋め込みが許可されていない可能性があります。\nマスには置きましたが、参加者の画面で再生できないかもしれません。";

function npcImageUrl(o) {
  return `/npc-image/${encodeURIComponent(o.id)}?v=${encodeURIComponent(o.videoId || 0)}`;
}

// ブラウン管テレビ風の枠(ベゼル・電源ランプ・脚)。中身の画面は呼び出し側が作って渡す
function buildTvFrame(screen) {
  const tv = document.createElement("div");
  tv.className = "npc-tv";
  const led = document.createElement("span");
  led.className = "npc-tv-led";
  tv.append(screen, led);
  return tv;
}

registerKind({
  key: "youtube",

  // playerは空のまま置いておき、普段は隠しておく。そのマスがYouTubeになったときだけ出す
  buildTileParts(tile) {
    const player = document.createElement("div");
    player.className = "tile-player";
    player.hidden = true;
    const playBtn = document.createElement("button");
    playBtn.type = "button";
    playBtn.className = "tile-play";
    playBtn.textContent = "▶";
    playBtn.title = "再生";
    playBtn.hidden = true;
    // 再生中はiframeがマスを覆ってクリックが親に届かなくなるので、拡大の入口を別に常設する
    const zoomBtn = document.createElement("button");
    zoomBtn.type = "button";
    zoomBtn.className = "tile-zoom";
    zoomBtn.hidden = true;
    // 再生状態はtile側に持つ。classListに持たせると、2秒ごとのrenderWorld()が
    // className を丸ごと書き換えるタイミングで消えてしまう
    Object.assign(tile, { player, playBtn, zoomBtn, playing: false, videoId: null, areaName: null });
    playBtn.addEventListener("click", e => { e.stopPropagation(); startTilePlayback(tile); });
    zoomBtn.addEventListener("click", e => { e.stopPropagation(); toggleTileFocus(tile); });
    return [player, playBtn, zoomBtn];
  },

  // 再生中のiframeは隠すだけでは音が止まらないので破棄する
  resetTile(tile) {
    tile.playBtn.hidden = tile.zoomBtn.hidden = true;
    tile.videoId = null;
    tile.areaName = null;
    stopTilePlayback(tile);
  },

  // 再生前はサムネと▶だけで、iframeはまだ存在しない
  renderTile(tile, area, { focused }) {
    setTileImage(tile, area, area.videoId);
    setClass(tile.el, `tile youtube${tile.playing ? " playing" : ""}${focused}`);
    tile.label.textContent = area.name;
    tile.status.hidden = true;
    tile.playBtn.hidden = tile.playing;
    tile.zoomBtn.hidden = false;
    tile.zoomBtn.textContent = focused ? "⤡" : "⤢";
    tile.zoomBtn.title = focused ? "マップに戻る" : "大きく見る";
    tile.videoId = area.videoId;
    tile.areaName = area.name;
  },

  // テレビの枠(.npc-tv)の中に、再生中(tile.playingNpcIdと一致)ならライブ埋め込みを、
  // そうでなければサムネ+▶(拡大時のみ)を出す。再生中はiframeがクリックを吸うので、
  // ステータスウィンドウを開く入口は画面ではなく枠のほうに持たせる
  renderCell(cell, o, { tile, roomLabel }) {
    const playing = o.id === tile.playingNpcId;
    const screen = document.createElement("div");
    screen.className = "npc-tv-screen";
    if (playing) {
      screen.appendChild(buildYouTubeEmbed(o.videoId, { autoplay: true }));
    } else {
      screen.style.backgroundImage = `url(${npcImageUrl(o)})`;
      const playBtn = document.createElement("button");
      playBtn.type = "button";
      playBtn.className = "npc-youtube-play";
      playBtn.title = "再生";
      playBtn.textContent = "▶";
      // display:noneで隠れている間(未拡大時)はクリックが発生しえないので、
      // ここでfocused判定をやり直す必要はない
      playBtn.addEventListener("click", e => {
        e.stopPropagation();
        startRoomNpcPlayback(tile, o);
      });
      screen.appendChild(playBtn);
    }
    const tv = buildTvFrame(screen);
    tv.classList.add("npc-youtube-tv");
    // playback.js/world.jsは再生中のセルをこのクラスで見分ける
    if (playing) tv.classList.add("npc-youtube-playing");
    tv.addEventListener("click", e => {
      // 縮小表示中はタイル全体クリック(ズーム用)に委ねる(openStatusOnClickと同じ)
      if (!tile.el.classList.contains("focused")) return;
      e.stopPropagation();
      // 部屋で流していた動画は、ウィンドウ側に引き継いで大きく流す(同時に鳴らせるのは1つだけ)
      if (playing) {
        stopAllPlayback();
        renderWorld();
      }
      openCharaStatus(o, null, roomLabel, { autoplay: playing });
    });
    cell.append(tv, buildBadge(o.name));
  },

  // 押したときだけbuildYouTubeEmbedでiframeを差し込む。他で再生中のタイルがあれば止める。
  // 部屋で再生中の枠から開いたとき(autoplay)は最初から埋め込んで再生する
  statusWide: true,
  renderStatus(container, o, roomLabel, { autoplay } = {}) {
    appendStatusRows(container, [["ルーム", statusRoomText(o, roomLabel)]]);
    const stage = document.createElement("div");
    stage.className = "npc-tv-screen status-yt-stage";
    const play = () => stage.replaceChildren(buildYouTubeEmbed(o.videoId, { autoplay: true }));
    if (autoplay) {
      play();
    } else {
      stage.style.backgroundImage = `url(${npcImageUrl(o)})`;
      const playBtn = document.createElement("button");
      playBtn.type = "button";
      playBtn.className = "status-yt-play";
      playBtn.textContent = "▶";
      playBtn.addEventListener("click", () => {
        stopAllPlayback();
        renderWorld(); // stopTilePlayback/stopRoomNpcPlayback自体は状態を倒すだけで見た目
                        // (▶やラベル)は次のrenderWorld()まで変わらないので、ここで即座に反映させる
        stage.style.backgroundImage = "";
        play();
      });
      stage.appendChild(playBtn);
    }
    container.appendChild(buildTvFrame(stage));
  },

  area: {
    label: "YouTubeルーム", needsUrl: true, addLabel: "置く", delLabel: "片付ける",
    confirm: "このYouTubeルームを片付けますか？", urlHint: "YouTubeの動画URL",
    nameHint: "表示名 (任意/未指定なら動画タイトル)", missingUrl: "YouTubeの動画URLを入力してください",
    swapHint: "別の動画URLに差し替え",
    embedWarning: VIDEO_EMBED_WARNING,
    title: a => `https://youtu.be/${a.videoId}`,
    text: a => `📺 ${a.name}`,
  },

  npc: {
    order: 3,
    label: "YouTube", addLabel: "入室させる", delLabel: "片付ける",
    confirm: "このYouTube NPCを片付けますか？",
    needsTask: false, needsImage: false, needsUrl: true,
    nameHint: "表示名 (任意/未指定なら動画タイトル)", urlHint: "YouTubeの動画URL",
    missingUrl: "YouTubeの動画URLを入力してください",
    embedWarning: VIDEO_EMBED_WARNING,
  },

  errors: {
    "invalid video": "YouTubeの動画URLとして読み取れませんでした",
    "video unavailable": "その動画の情報を取得できませんでした(限定公開・削除済みかもしれません)",
  },
});
