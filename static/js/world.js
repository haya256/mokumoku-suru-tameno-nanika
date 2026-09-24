// ワールドマップ(3×3のマス)と、マスの中の部屋(9セル)の描画。
// マスや部屋セルの中身のうち種別ごとに違う部分は、kinds/ の各種別に任せる

// マスは9つ作ったきり使い回す。毎pollで作り直すとキャラのCSSアニメーションがリセットされるため
const tiles = [];
for (let i = 0; i < 9; i++) {
  const el = document.createElement("div");
  el.className = "tile empty";
  const img = document.createElement("img");
  img.alt = "";
  img.addEventListener("error", () => img.classList.add("missing"));
  img.addEventListener("load", () => img.classList.remove("missing"));
  const overlay = document.createElement("div");
  overlay.className = "room-overlay";
  for (let r = 0; r < ROOM_COUNT; r++) {
    const cell = document.createElement("div");
    cell.className = "cell";
    overlay.appendChild(cell);
  }
  const label = document.createElement("span");
  label.className = "tile-label";
  const status = document.createElement("span");
  status.className = "tile-status";
  status.hidden = true;
  // 自分のルームが「準備中/Closed」のときだけ使う演出用オーバーレイ(管理者操作、renderWorld参照)
  const roomStateOverlay = document.createElement("div");
  roomStateOverlay.className = "tile-room-state";
  roomStateOverlay.hidden = true;
  const roomStateText = document.createElement("span");
  roomStateOverlay.appendChild(roomStateText);
  const tile = { el, img, overlay, label, status,
                 roomStateOverlay, roomStateText,
                 // 部屋セルのうち、見えている間は毎pollの手入れが要るもの(時計NPCの位相合わせなど)。
                 // occupant id -> 手入れ関数。renderRoomIntoがセルを作り直すたびに詰め直す
                 liveCells: new Map(),
                 // 部屋セル内で再生中のYouTube NPC(あれば)のid/表示名。tile.playing(エリア用)とは
                 // 別に持つ(1つのtileが同時に両方を再生することはない設計だが、意味が違うので分ける)
                 playingNpcId: null, playingNpcName: null,
                 cells: [...overlay.children], key: null, lastState: "" };
  // 種別ごとの常設部品(YouTubeのプレイヤー、時計の文字盤など)。普段は隠れていて、
  // そのマスがその種別になったときだけCSS(.tile.<種別>)で出す
  const parts = kindList().flatMap(k => k.buildTileParts?.(tile) || []);
  el.append(img, overlay, label, status, ...parts, roomStateOverlay);
  worldMapEl.appendChild(el);
  tiles.push(tile);
}

// 1部屋ぶんの中身(キャラと名前バッジ)を描く。自分のルームにもピアのルームにも使う。
// charaUrl はカスタム画像のURLを組み立てる関数(自分とピアで参照先が変わる)。
// roomLabel はステータスウィンドウでの表示用(自分ならnull、ピアなら相手ルーム名)
// visible はこのタイルが今画面に見えているか(時計エリアと同じ意味・同じ値)。
// 時計NPCの位相合わせは下部でfingerprintの変化と無関係に毎回チェックするため必要
function renderRoomInto(tile, entries, charaUrl, roomLabel, visible) {
  // ポーズ(0〜2)は入室時にサーバーが決めて退室まで固定。ピア由来の値は信用せず範囲に丸める。
  // npc/kindはNPC機能由来のフィールドで、実参加者やkind未指定のNPCはbasic扱いにフォールバックする
  const occupants = (entries || []).map(e => ({
    id: String(e.id ?? ""), room: e.room, name: String(e.name ?? ""), task: String(e.task ?? ""),
    start: String(e.start ?? ""), end: String(e.end ?? ""),
    pose: Math.min(2, Math.max(0, Math.trunc(e.pose) || 0)), imgv: e.imgv || 0,
    npc: !!e.npc, kind: e.kind || "basic", videoId: String(e.videoId ?? ""),
  }));
  // 再生中のYouTube NPCが退室していたら再生状態を破棄する(次のポーリングで気づく)
  if (tile.playingNpcId && !occupants.some(o => o.id === tile.playingNpcId)) {
    tile.playingNpcId = null;
    tile.playingNpcName = null;
  }
  // 変化があればDOMを作り直す(作り直すとCSSアニメーションがリセットされるので、変化が
  // 無ければ触らない)。種別によっては入退室が無くても描き直したいので(カレンダーNPCなら
  // 日付が変わったとき)、その種別が出す値もフィンガープリントに足す。再生中のNPCも
  // フィンガープリントに含め、再生開始/停止の切り替わりを確実に1回は反映させる
  const extra = [...new Set(occupants.map(o => occupantKind(o.kind).cellFingerprint?.()).filter(v => v != null))];
  const state = JSON.stringify({ occupants, extra, playing: tile.playingNpcId });
  if (state !== tile.lastState) {
    tile.lastState = state;
    // 再生中のYouTube NPCが入っているセルは、他の入退室で作り直すと再生が途切れて
    // しまうので触らない。ただし「DOMに.npc-youtube-playingがある」だけでは、そのNPCが
    // 片付けられた後も(tile.playingNpcIdは上でnullに戻っているのに)古いiframeを
    // 温存し続けてしまう(退室後も再生が止まらないバグの原因だった)。
    // 今のoccupantsと照らして「まだそのマスに居る、かつ今も再生対象である」ときだけ温存する
    const stillPlayingRoom = occupants.find(o => o.id === tile.playingNpcId)?.room;
    tile.cells.forEach((cell, i) => {
      if (i + 1 === stillPlayingRoom && cell.querySelector(".npc-youtube-playing")) return;
      cell.innerHTML = "";
    });
    tile.liveCells.clear();
    occupants.forEach(o => {
      const cell = tile.cells[o.room - 1];
      if (!cell) return;
      if (o.room === stillPlayingRoom && o.id === tile.playingNpcId && cell.querySelector(".npc-youtube-playing")) return;
      occupantKind(o.kind).renderCell(cell, o, { tile, roomLabel, charaUrl });
    });
  }
  // 見えている間はfingerprintが変わらなくても毎pollチェックする(時計の位相合わせなど。
  // 非表示中に直しても無駄なうえ、表示された瞬間にCSSアニメーションが作り直した時刻で復活するため)
  if (visible) tile.liveCells.forEach(upkeep => upkeep());
}

// 部屋セルの名前バッジ
function buildBadge(name) {
  const badge = document.createElement("span");
  badge.className = "badge";
  badge.textContent = name;
  return badge;
}

// セルの中身をクリックしたらステータスウィンドウを開く。portraitは肖像のクロップ情報(無ければnull)
function openStatusOnClick(el, o, portrait, tile, roomLabel) {
  el.addEventListener("click", e => {
    // 縮小表示中は何もしない。タイル全体クリック(ズーム用)にそのまま委ねる
    if (!tile.el.classList.contains("focused")) return;
    e.stopPropagation();
    openCharaStatus(o, portrait, roomLabel);
  });
}

function selfCharaUrl(o) {
  return `/chara-custom/${encodeURIComponent(o.id)}.png?v=${o.imgv}`;
}

function peerCharaUrl(peerId) {
  return o => `/peer-chara/${encodeURIComponent(peerId)}/${encodeURIComponent(o.id)}.png?v=${o.imgv}`;
}

const charaStatusOverlay = document.getElementById("charaStatusOverlay");
const charaStatusWindow = document.getElementById("charaStatusWindow");
const charaStatusName = document.getElementById("charaStatusName");
const charaStatusPortrait = document.getElementById("charaStatusPortrait");
const charaStatusText = document.getElementById("charaStatusText");
const charaStatusCloseBtn = document.getElementById("charaStatusCloseBtn");

function statusRoomText(o, roomLabel) {
  return roomLabel ? `${roomLabel} #${o.room}` : `Room ${o.room}`;
}

// ステータスウィンドウの「見出し: 値」の行。rowsは [見出し, 値] の配列
function appendStatusRows(container, rows) {
  rows.forEach(([label, value]) => {
    const row = document.createElement("div");
    row.className = "row";
    const l = document.createElement("span"); l.className = "label"; l.textContent = label;
    const v = document.createElement("span"); v.className = "value"; v.textContent = value;
    row.append(l, v);
    container.appendChild(row);
  });
}

// アバタークリックで開くステータスウィンドウ。中身は種別ごとに出し分ける(renderStatus)
function openCharaStatus(o, portrait, roomLabel, opts = {}) {
  const kind = KINDS[o.kind]?.renderStatus ? KINDS[o.kind] : KINDS.basic;
  charaStatusWindow.classList.toggle("wide", !!kind.statusWide);
  charaStatusName.textContent = o.name;
  charaStatusPortrait.hidden = !portrait;
  if (portrait) {
    charaStatusPortrait.classList.toggle("custom", portrait.custom);
    charaStatusPortrait.style.backgroundImage = portrait.custom ? `url(${portrait.url})` : "";
    charaStatusPortrait.style.backgroundPosition = portrait.custom ? "" : portrait.position;
  }
  charaStatusText.innerHTML = "";
  kind.renderStatus(charaStatusText, o, roomLabel, opts);
  charaStatusOverlay.hidden = false;
}

function closeCharaStatus() {
  charaStatusOverlay.hidden = true;
  // hiddenだけではYouTube NPCのiframeの音が止まらないので中身ごと破棄する
  // (stopTilePlaybackがreplaceChildren()で確実に取り除いているのと同じ理由)
  charaStatusText.innerHTML = "";
}

charaStatusCloseBtn.addEventListener("click", closeCharaStatus);
// 背景(ウィンドウの外側)クリックで閉じる。ウィンドウ内クリックはtargetがwindow配下になるので閉じない
charaStatusOverlay.addEventListener("click", e => {
  if (e.target === charaStatusOverlay) closeCharaStatus();
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && !charaStatusOverlay.hidden) closeCharaStatus();
});

// エリアをマスに割り当てる。slotが重複・欠損していても(設定を手で編集した場合など)
// 空いているマスに寄せて必ずどこかに出す
function assignTiles() {
  const assigned = new Array(9).fill(null);
  assigned[SELF_INDEX] = { self: true };
  const overflow = [];
  areas.forEach(a => {
    const idx = SLOT_TO_INDEX[a.slot];
    if (idx !== undefined && !assigned[idx]) assigned[idx] = { area: a };
    else overflow.push(a);
  });
  overflow.forEach(a => {
    const idx = assigned.findIndex(x => !x);
    if (idx >= 0) assigned[idx] = { area: a };
  });
  return assigned;
}

function setClass(el, cls) {
  if (el.className !== cls) el.className = cls;
}

// サーバーがマス絵をまだ中継できない間はsrcを付けない。
// ここで404を踏ませると、あとで取得できてもURLが変わらず再読み込みが走らないため、
// 画像が出ないまま(キャラだけが浮いた状態)になってしまう。
// verは変化検知用で、ピアなら相手の部屋画像バージョン、YouTubeなら動画IDを渡す
function setTileImage(tile, area, ver) {
  if (!area.hasImage) {
    if (tile.img.getAttribute("src")) tile.img.removeAttribute("src");
    tile.img.classList.add("missing");
    return;
  }
  // 拡張子は付けない。webp(native)/png(fork)/jpeg(youtube)と形式が違うので、mimeはサーバーが返す
  const src = `/area-image/${encodeURIComponent(area.id)}?v=${encodeURIComponent(ver || 0)}`;
  if (tile.img.getAttribute("src") !== src) tile.img.src = src;
}

// マスを別のエリアに明け渡す前の後始末。種別ごとの部品(再生中のiframeなど)は各種別が片付ける
// (.tile.empty のCSSはimg/overlay/label/statusしか隠さない)
function resetTile(tile) {
  tile.key = null;
  tile.lastState = "";
  tile.status.hidden = true;
  tile.roomStateOverlay.hidden = true;
  kindList().forEach(k => k.resetTile?.(tile));
}

function renderWorld() {
  // エリアが1つも無いときはマップにせず、今までどおり自分のルームを全画面で出す
  const focus = areas.length === 0 ? "self" : focusedKey;
  worldMapEl.classList.toggle("focus-mode", focus !== null);
  assignTiles().forEach((slot, i) => {
    const tile = tiles[i];
    if (!slot) {
      // 解除した直後は「接続できません」や再生中のプレイヤーが残っているので片付ける
      if (tile.key !== null) resetTile(tile);
      setClass(tile.el, "tile empty");
      return;
    }
    const key = slot.self ? "self" : slot.area.id;
    // 同じマスが別のエリアに変わったときも、前のエリアの残骸を持ち越さない
    if (tile.key !== key) { resetTile(tile); tile.key = key; }
    const focused = focus === key ? " focused" : "";
    // 拡大表示中は他のマスがdisplay:noneになり、CSSアニメーションが破棄される。
    // 見えていないマスの針を合わせても無駄(表示された瞬間にその時刻で復活してしまう)なので、
    // 実際に見えているかどうかを時計エリアにも部屋セル内の時計NPCにも渡す
    const visible = focus === null || focus === key;
    if (slot.self) {
      if (tile.img.getAttribute("src") !== selfRoomImageSrc) tile.img.src = selfRoomImageSrc;
      setClass(tile.el, `tile self${focused}`);
      tile.label.textContent = `${roomTitleEl.textContent}（このルーム）`;
      tile.status.hidden = true;
      renderRoomInto(tile, lastEntries, selfCharaUrl, null, visible);
      const stateLabel = ROOM_STATE_LABELS[roomState];
      tile.roomStateOverlay.hidden = !stateLabel;
      if (stateLabel) tile.roomStateText.textContent = stateLabel;
      return;
    }
    const kind = KINDS[slot.area.kind];
    if (kind?.renderTile) {
      kind.renderTile(tile, slot.area, { focused, visible });
    } else {
      // 知らない種別(設定を手で編集した場合など)。霧のマスにして何も壊さない
      resetTile(tile);
      setClass(tile.el, "tile empty");
    }
  });
  renderNowPlaying();
  backToMapBtn.hidden = !(areas.length > 0 && focusedKey !== null);
}

function toggleTileFocus(tile) {
  focusedKey = focusedKey === tile.key ? null : tile.key;
  renderWorld();
}

// ▶と拡大ボタンは自前のハンドラでstopPropagationしているので、ここには上がってこない
worldMapEl.addEventListener("click", e => {
  if (areas.length === 0) return; // エリアなしのときは常に自分のルームの全画面
  const tile = tiles.find(t => t.el === e.target.closest(".tile"));
  if (!tile || !tile.key || focusedKey === tile.key) return;
  focusedKey = tile.key;
  renderWorld();
});

// タブから戻ってきたときとbfcacheから復元されたとき。タブが隠れていただけなら針は
// 進んでいるが、OSがスリープしていた場合はアニメーションの時計だけが止まって遅れる。
// 2秒後のpollを待たずその場で描き直す(ずれていなければ何も起きない)
const resyncClocks = () => renderWorld();
document.addEventListener("visibilitychange", () => { if (!document.hidden) resyncClocks(); });
window.addEventListener("pageshow", resyncClocks);

backToMapBtn.addEventListener("click", () => {
  focusedKey = null;
  renderWorld();
});
