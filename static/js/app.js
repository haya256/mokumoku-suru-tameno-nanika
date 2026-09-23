const messagesEl = document.getElementById("messages");
const entriesEl = document.getElementById("entries");
const form = document.getElementById("form");
const nameEl = document.getElementById("name");
const textEl = document.getElementById("text");
const taskEl = document.getElementById("task");
const startEl = document.getElementById("start");
const endEl = document.getElementById("end");
const charaEl = document.getElementById("chara");
const msgImageEl = document.getElementById("msgImage");
const attachImageBtn = document.getElementById("attachImageBtn");
const pendingImageRow = document.getElementById("pendingImageRow");
const pendingImagePreview = document.getElementById("pendingImagePreview");
const removePendingImageBtn = document.getElementById("removePendingImageBtn");
const joinRow = document.getElementById("joinRow");
const statusRow = document.getElementById("statusRow");
const viewOnlyRow = document.getElementById("viewOnlyRow");
const goReceptionBtn = document.getElementById("goReceptionBtn");
const myStatusEl = document.getElementById("myStatus");
const joinBtn = document.getElementById("joinBtn");
const editBtn = document.getElementById("editBtn");
const leaveBtn = document.getElementById("leaveBtn");
const cancelEditBtn = document.getElementById("cancelEditBtn");
const recordRow = document.getElementById("recordRow");
const recordText = document.getElementById("recordText");
const copyBtn = document.getElementById("copyBtn");
const closeRecordBtn = document.getElementById("closeRecordBtn");
const discordStatusEl = document.getElementById("discordStatus");
const roomViewEl = document.getElementById("roomView");
const worldMapEl = document.getElementById("worldMap");
const backToMapBtn = document.getElementById("backToMapBtn");
const nowPlayingBar = document.getElementById("nowPlayingBar");
const nowPlayingLabel = document.getElementById("nowPlayingLabel");
const nowPlayingGoBtn = document.getElementById("nowPlayingGoBtn");
const nowPlayingStopBtn = document.getElementById("nowPlayingStopBtn");

let editing = false;
let receptionOpen = false;
let lastEntries = [];
// マップに置かれたエリアの最新状態(/world の戻り値)。0件なら従来どおり自分のルームの全画面表示。
// kind="peer" はつながった相手ルーム、kind="youtube" は管理者が置いた動画のマス
let areas = [];
// 在室者一覧とチャットのマージに使うのは相手ルームだけ(ガジェットには参加者もチャットも無い)
const peerAreas = () => areas.filter(a => a.kind === "peer");
// 拡大表示中のマス。null=ワールドマップ表示 / "self"=自分のルーム / それ以外はエリアのid
let focusedKey = null;
let localMessages = [];
let selfRoomImageSrc = "/room-image.webp";
// 合言葉欄に管理者合言葉を入れた場合にtrueになる(サーバー側が都度判定。ここはボタン表示のためだけのキャッシュ)
let isAdmin = false;
let prevIsAdmin = false; // isAdminの変化点でだけボタンを付け外しする(毎ポーリングで作り直さない)
// 部屋画像のバージョン。nullは「まだ基準値を持っていない」状態(初回pollで基準値として記録するだけで再取得はしない)
let roomImageVersion = null;
let pendingImageVersion = null; // ジッター待ち中のバージョン(同じ変化に対して二重にsetTimeoutしない)
// ルームの見た目状態。normal以外なら自分のルームに演出オーバーレイを出す(renderWorld参照)
let roomState = "normal";
const ROOM_STATE_LABELS = { preparing: "準備中", closed: "～ おしまい ～\nご参加、ご視聴ありがとうございました！" };
nameEl.value = localStorage.getItem("mokumoku-name") || "";
// 入室を待たず、名前欄の変更時点で即保存する
nameEl.addEventListener("input", () => {
  localStorage.setItem("mokumoku-name", nameEl.value.trim());
});

// 本人識別用ID(ブラウザごとに固定)。名前は表示用なので変更しても別人にならない
// ※crypto.randomUUIDはLAN経由のhttpアクセス(非セキュアコンテキスト)では使えないため自前生成
let clientId = localStorage.getItem("mokumoku-id");
if (!clientId) {
  clientId = Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  localStorage.setItem("mokumoku-id", clientId);
}
const ROOM_COUNT = 9;
// 3×3マップの中央は自分のルーム固定。ピアのslot(0〜7)は周囲8マスに対応する
const SELF_INDEX = 4;
const SLOT_TO_INDEX = [0, 1, 2, 3, 5, 6, 7, 8];

// 時計の文字盤。viewBoxで座標を固定するので、マスが120pxでも700pxでも破綻しない。
// 中心を(50,45)と上寄りにしてあるのは、下端の .tile-label(黒帯)が小さいマスでは
// 高さの14%ほどを占めるため。半径35.5+線幅1.5で文字盤の下端は82になり、帯と当たらない。
// 針は時刻を読み上げられないので、支援技術には丸ごと隠す
const CLOCK_FACE_SVG = `
  <svg viewBox="0 0 100 100" aria-hidden="true">
    <circle cx="50" cy="45" r="35.5" fill="#f2ead8" stroke="#3b4252" stroke-width="3"/>
    ${[...Array(12)].map((_, i) => {
      const major = i % 3 === 0;  // 12/3/6/9 だけ太く長くする
      return `<line x1="50" y1="13" x2="50" y2="${major ? 18 : 16}"
                    stroke="#3b4252" stroke-width="${major ? 3 : 1.5}"
                    transform="rotate(${i * 30} 50 45)"/>`;
    }).join("")}
    ${[12, 3, 6, 9].map((n, i) => {
      const a = (i * 90 - 90) * Math.PI / 180;  // 12時を上にするため-90度回す
      // 目盛りは中心から半径27まで伸びているので、数字はその内側(半径21)に置く
      return `<text class="numeral" x="${50 + Math.cos(a) * 21}" y="${45 + Math.sin(a) * 21}"
                    text-anchor="middle" dominant-baseline="central"
                    font-size="9" font-weight="bold" fill="#3b4252">${n}</text>`;
    }).join("")}
    <line class="hand hour" x1="50" y1="51" x2="50" y2="27" stroke="#3b4252" stroke-width="4.5"/>
    <line class="hand min"  x1="50" y1="53" x2="50" y2="18" stroke="#3b4252" stroke-width="3"/>
    <line class="hand sec"  x1="50" y1="55" x2="50" y2="15" stroke="#c0392b" stroke-width="1.5"/>
    <circle cx="50" cy="45" r="2.5" fill="#3b4252"/>
  </svg>`;

const CALENDAR_WEEKDAYS = ["日", "月", "火", "水", "木", "金", "土"];

// 和暦の元号+年。改元テーブルを自前で持たず、Intlの日本暦カレンダーに委ねる
// (Node/主要ブラウザとも ja-JP-u-ca-japanese をサポート)
function japaneseEraYear(date) {
  const parts = new Intl.DateTimeFormat("ja-JP-u-ca-japanese", { era: "short", year: "numeric" })
    .formatToParts(date);
  const era = parts.find(p => p.type === "era")?.value || "";
  const year = parts.find(p => p.type === "year")?.value || "";
  return `${era}${year}`;
}

// 「2026(令和8)年9月」のような年月見出し。未拡大の年月表示と、拡大時のグリッド見出しの両方で使う
function formatYearMonth(date, monthIndex) {
  return `${date.getFullYear()}(${japaneseEraYear(date)})年${monthIndex + 1}月`;
}

// ある年月の日付セルのHTML。日曜始まり(日本の慣習)。今日がその年月と一致するときだけ
// 該当日に .today を付ける。前後月の余白セルは空にして日数だけを目立たせ、
// 最後の週を7の倍数まで埋めて月によって高さがガタつかないようにする
function buildCalendarGrid(year, monthIndex, today) {
  const first = new Date(year, monthIndex, 1);
  const daysInMonth = new Date(year, monthIndex + 1, 0).getDate();
  const startWeekday = first.getDay();
  const isThisMonth = today.getFullYear() === year && today.getMonth() === monthIndex;
  const cells = [];
  for (let i = 0; i < startWeekday; i++) cells.push('<span class="cal-day empty"></span>');
  for (let d = 1; d <= daysInMonth; d++) {
    const isToday = isThisMonth && d === today.getDate();
    cells.push(`<span class="cal-day${isToday ? " today" : ""}">${d}</span>`);
  }
  while (cells.length % 7 !== 0) cells.push('<span class="cal-day empty"></span>');
  const head = CALENDAR_WEEKDAYS.map(w => `<span class="cal-weekday">${w}</span>`).join("");
  return `<div class="cal-month">${formatYearMonth(first, monthIndex)}</div>
    <div class="cal-grid">${head}${cells.join("")}</div>`;
}

// カレンダーの文字盤全体。未拡大用(年月+大きな数字+曜日)と拡大用(月グリッド)を両方作っておき、
// どちらを見せるかはCSSの.focusedだけで切り替える(表示されていない側はdisplay:noneなので
// アクセシビリティツリーにも重複して出ない)
function buildCalendarFaceHTML(today) {
  const weekday = CALENDAR_WEEKDAYS[today.getDay()];
  return `
    <div class="cal-compact">
      <div class="cal-yearmonth">${formatYearMonth(today, today.getMonth())}</div>
      <div class="cal-daynum">${today.getDate()}</div>
      <div class="cal-weekday-solo">${weekday}</div>
    </div>
    <div class="cal-full">${buildCalendarGrid(today.getFullYear(), today.getMonth(), today)}</div>`;
}

// 日付が変わったかどうかの比較キー。renderCalendarTile(エリア)とrenderRoomInto(カレンダーNPC)の
// 両方で「日付が変わったときだけ再描画する」ために使う共通の形式
function calendarDateKey(date) {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

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
  // YouTubeエリア用。普段は隠しておき、そのマスがYouTubeになったときだけ出す。
  // playerは空のまま置いておき、▶が押された時点で初めてiframeを差し込む
  // (置いただけでiframeを作ると、マップを開いただけでYouTubeとの通信と再生が始まってしまう)
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
  // 時計エリア用。document.createElement("svg") はHTMLUnknownElementになって
  // 何も描画されないので、文字列をinnerHTMLで流し込んでSVGとして解釈させる
  const face = document.createElement("div");
  face.className = "clock-face";
  face.innerHTML = CLOCK_FACE_SVG;
  // カレンダーエリア用。時計と違ってCSSアニメーションを使わないので参照保持の必要はなく、
  // 日付が変わったときだけ丸ごと書き換える(calendarKeyで判定、renderCalendarTile参照)
  const calFace = document.createElement("div");
  calFace.className = "calendar-face";
  // ブラウザエリア用。YouTubeのplayerと違い、エリアが割り当てられた瞬間(クリック不要)に
  // iframeを作る。中身はrenderBrowserTile/resetTileがreplaceChildrenで出し入れする
  const browserFrame = document.createElement("div");
  browserFrame.className = "browser-frame";
  // 自分のルームが「準備中/Closed」のときだけ使う演出用オーバーレイ(管理者操作、renderWorld参照)
  const roomStateOverlay = document.createElement("div");
  roomStateOverlay.className = "tile-room-state";
  roomStateOverlay.hidden = true;
  const roomStateText = document.createElement("span");
  roomStateOverlay.appendChild(roomStateText);
  el.append(img, overlay, label, status, player, playBtn, zoomBtn, face, calFace, browserFrame, roomStateOverlay);
  worldMapEl.appendChild(el);
  const tile = { el, img, overlay, label, status, player, playBtn, zoomBtn, face,
                 hands: { hour: face.querySelector(".hand.hour"), min: face.querySelector(".hand.min"),
                          sec: face.querySelector(".hand.sec") },
                 calendarFace: calFace, calendarKey: null,
                 browserFrame, browserUrl: null,
                 roomStateOverlay, roomStateText,
                 // 部屋セル内の時計NPCの針(occupant id -> {hour,min,sec})。renderRoomIntoが
                 // セルを作り直すたびに詰め直し、見えている間は毎pollここを見て位相ズレを直す
                 roomClockHands: new Map(),
                 // 部屋セル内で再生中のYouTube NPC(あれば)のid/表示名。tile.playing(エリア用)とは
                 // 別に持つ(1つのtileが同時に両方を再生することはない設計だが、意味が違うので分ける)
                 playingNpcId: null, playingNpcName: null,
                 cells: [...overlay.children], key: null, lastState: "", playing: false };
  // 再生状態はtile側に持つ。classListに持たせると、2秒ごとのrenderWorld()が
  // className を丸ごと書き換えるタイミングで消えてしまう
  playBtn.addEventListener("click", e => { e.stopPropagation(); startTilePlayback(tile); });
  zoomBtn.addEventListener("click", e => { e.stopPropagation(); toggleTileFocus(tile); });
  tiles.push(tile);
}

let lastMsgSig = "";

function render(msgs) {
  // マージ後は件数だけでは変化を判定できない(ピアの取得遅れで途中に挿入されうる)ため、
  // 件数と末尾のタイムスタンプを繋げたシグネチャで比べる
  const sig = `${msgs.length}|${msgs.length ? msgs[msgs.length - 1].ts : 0}`;
  if (sig === lastMsgSig) return;
  lastMsgSig = sig;
  messagesEl.innerHTML = "";
  msgs.forEach(m => {
    const div = document.createElement("div");
    // m.from はピア由来のときだけ入る発信元ルーム名
    const from = m.from ? `<span class="from">${esc(m.from)}</span>` : "";
    const remote = m.from ? " remote" : "";
    if (m.system) {
      div.className = `msg system${remote}`;
      div.innerHTML = `<span class="stamp">${esc(m.time)}</span>${from}${esc(m.text)}`;
    } else {
      div.className = `msg${remote}`;
      div.innerHTML = `<div class="meta">${from}<span>${esc(m.name)}</span> ${esc(m.time)}</div>`;
      const textEl = document.createElement("div");
      textEl.className = "text";
      const videoId = appendLinkedText(textEl, m.text);
      div.appendChild(textEl);
      if (videoId) div.appendChild(buildYouTubeEmbed(videoId));
      if (m.image) div.appendChild(buildMsgImage(m));
    }
    messagesEl.appendChild(div);
  });
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// 1部屋ぶんの中身(キャラと名前バッジ)を描く。自分のルームにもピアのルームにも使う。
// charaUrl はカスタム画像のURLを組み立てる関数(自分とピアで参照先が変わる)。
// roomLabel はステータスウィンドウでの表示用(自分ならnull、ピアなら相手ルーム名)
// visible はこのタイルが今画面に見えているか(renderClockTileと同じ意味・同じ値)。
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
  // 無ければ触らない)。カレンダーNPCが1体でもいる場合は、他の入退室が無くても日付が
  // 変わったら再描画したいのでフィンガープリントに今日の日付キーを足す。再生中のNPCも
  // フィンガープリントに含め、再生開始/停止の切り替わりを確実に1回は反映させる
  const hasCalendarNpc = occupants.some(o => o.kind === "calendar");
  const state = JSON.stringify({
    occupants, today: hasCalendarNpc ? calendarDateKey(new Date()) : null, playing: tile.playingNpcId,
  });
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
    tile.roomClockHands.clear();
    occupants.forEach(o => {
      const cell = tile.cells[o.room - 1];
      if (!cell) return;
      if (o.room === stillPlayingRoom && o.id === tile.playingNpcId && cell.querySelector(".npc-youtube-playing")) return;
      if (o.kind === "calendar") {
        renderCalendarNpcCell(cell, o, tile, roomLabel);
        return;
      }
      if (o.kind === "clock") {
        renderClockNpcCell(cell, o, tile, roomLabel);
        return;
      }
      if (o.kind === "youtube") {
        renderYoutubeNpcCell(cell, o, tile, roomLabel);
        return;
      }
      const chara = document.createElement("div");
      chara.className = "chara";
      // ステータスウィンドウの肖像に同じクロップをそのまま使い回すための情報(再計算しない)
      let portrait;
      if (o.imgv) {
        // アップロードされたカスタム画像(imgvはキャッシュバスター兼差分検知用)
        chara.classList.add("custom");
        const url = charaUrl(o);
        chara.style.backgroundImage = `url(${url})`;
        portrait = { custom: true, url };
      } else {
        const col = ((o.room - 1) % 3) * 3 + o.pose;
        const row = Math.floor((o.room - 1) / 3) * 2;
        const position = `${col / 8 * 100}% ${row / 5 * 100}%`;
        chara.style.backgroundPosition = position;
        portrait = { custom: false, position };
      }
      chara.style.animationDelay = `${(o.room * 0.3) % 2}s`;
      chara.addEventListener("click", e => {
        // 縮小表示中は何もしない。タイル全体クリック(ズーム用)にそのまま委ねる
        if (!tile.el.classList.contains("focused")) return;
        e.stopPropagation();
        openCharaStatus(o, portrait, roomLabel);
      });
      cell.appendChild(chara);
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = o.name;
      badge.title = o.task;
      cell.appendChild(badge);
    });
  }
  // 時計NPCの位相合わせ。時計エリア(renderClockTile)と同じ理由で、見えている間は
  // fingerprintが変わらなくても毎pollチェックする(非表示中に直しても無駄なうえ、
  // 表示された瞬間にCSSアニメーションが作り直した時刻で復活するため)
  if (visible) {
    tile.roomClockHands.forEach(hands => { if (clockNeedsSync(hands)) syncClockHands(hands); });
  }
}

// カレンダーNPC専用のセル中身。通常のキャラスプライトの代わりにワールドマップのカレンダー
// エリアと同じ文字盤(コンパクト/月グリッドの切り替えもCSSで無改修のまま流用)を小さく置く。
// ポートレート(肖像)の概念を持たないのでopenCharaStatusにはportrait=nullを渡す
function renderCalendarNpcCell(cell, o, tile, roomLabel) {
  const face = document.createElement("div");
  face.className = "calendar-face";
  face.innerHTML = buildCalendarFaceHTML(new Date());
  face.addEventListener("click", e => {
    if (!tile.el.classList.contains("focused")) return;
    e.stopPropagation();
    openCharaStatus(o, null, roomLabel);
  });
  cell.appendChild(face);
  const badge = document.createElement("span");
  badge.className = "badge";
  badge.textContent = o.name;
  cell.appendChild(badge);
}

// 時計NPC専用のセル中身。ワールドマップの時計エリアと同じCLOCK_FACE_SVGを小さく置く。
// 針はCSSアニメーションで回るので、ここでは初期位相を合わせてtile.roomClockHandsに登録するだけ
// (以降の位相ズレの再チェックはrenderRoomInto末尾がvisible時に毎poll行う)
function renderClockNpcCell(cell, o, tile, roomLabel) {
  const face = document.createElement("div");
  face.className = "clock-face";
  face.innerHTML = CLOCK_FACE_SVG;
  const hands = { hour: face.querySelector(".hand.hour"), min: face.querySelector(".hand.min"),
                  sec: face.querySelector(".hand.sec") };
  syncClockHands(hands);
  tile.roomClockHands.set(o.id, hands);
  face.addEventListener("click", e => {
    if (!tile.el.classList.contains("focused")) return;
    e.stopPropagation();
    openCharaStatus(o, null, roomLabel);
  });
  cell.appendChild(face);
  const badge = document.createElement("span");
  badge.className = "badge";
  badge.textContent = o.name;
  cell.appendChild(badge);
}

// YouTube NPC専用のセル中身。再生中(tile.playingNpcIdと一致)ならライブ埋め込みを、
// そうでなければサムネ+▶(拡大時のみ)を出す。サムネ本体のクリックはステータスウィンドウを開く
function renderYoutubeNpcCell(cell, o, tile, roomLabel) {
  if (o.id === tile.playingNpcId) {
    const wrap = document.createElement("div");
    wrap.className = "npc-youtube-playing";
    wrap.appendChild(buildYouTubeEmbed(o.videoId, { autoplay: true }));
    cell.appendChild(wrap);
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = o.name;
    cell.appendChild(badge);
    return;
  }
  const thumb = document.createElement("div");
  thumb.className = "npc-youtube-thumb";
  thumb.style.backgroundImage = `url(${npcImageUrl(o)})`;
  thumb.addEventListener("click", e => {
    if (!tile.el.classList.contains("focused")) return;
    e.stopPropagation();
    openCharaStatus(o, null, roomLabel);
  });
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
  thumb.appendChild(playBtn);
  cell.appendChild(thumb);
  const badge = document.createElement("span");
  badge.className = "badge";
  badge.textContent = o.name;
  cell.appendChild(badge);
}

function selfCharaUrl(o) {
  return `/chara-custom/${encodeURIComponent(o.id)}.png?v=${o.imgv}`;
}

function peerCharaUrl(peerId) {
  return o => `/peer-chara/${encodeURIComponent(peerId)}/${encodeURIComponent(o.id)}.png?v=${o.imgv}`;
}

function npcImageUrl(o) {
  return `/npc-image/${encodeURIComponent(o.id)}?v=${encodeURIComponent(o.videoId || 0)}`;
}

const charaStatusOverlay = document.getElementById("charaStatusOverlay");
const charaStatusName = document.getElementById("charaStatusName");
const charaStatusPortrait = document.getElementById("charaStatusPortrait");
const charaStatusText = document.getElementById("charaStatusText");
const charaStatusCloseBtn = document.getElementById("charaStatusCloseBtn");

// アバタークリックで開くステータスウィンドウの中身をkindごとに出し分ける
// (AREA_KINDS/NPC_KINDSと同じ思想)。将来「カレンダーNPC」等を足すときはここにエントリを増やす
const CHARA_STATUS_KINDS = {
  basic: {
    render(container, o, roomLabel) {
      const rows = [
        ["ルーム", roomLabel ? `${roomLabel} #${o.room}` : `Room ${o.room}`],
        ["時間", `${o.start || "?"}〜${o.end || "?"}`],
        ["やること", o.task || "(未入力)"],
      ];
      rows.forEach(([label, value]) => {
        const row = document.createElement("div");
        row.className = "row";
        const l = document.createElement("span"); l.className = "label"; l.textContent = label;
        const v = document.createElement("span"); v.className = "value"; v.textContent = value;
        row.append(l, v);
        container.appendChild(row);
      });
    },
  },
  // ワールドマップのカレンダーエリアと同じ月グリッドを表示する。時間・やることは意味を
  // 持たないので出さない。ポートレートも持たないのでopenCharaStatus側でportrait=nullとして扱う
  calendar: {
    render(container, o, roomLabel) {
      const row = document.createElement("div");
      row.className = "row";
      const l = document.createElement("span"); l.className = "label"; l.textContent = "ルーム";
      const v = document.createElement("span"); v.className = "value";
      v.textContent = roomLabel ? `${roomLabel} #${o.room}` : `Room ${o.room}`;
      row.append(l, v);
      container.appendChild(row);

      const today = new Date();
      const face = document.createElement("div");
      face.className = "calendar-face";
      face.innerHTML = buildCalendarGrid(today.getFullYear(), today.getMonth(), today);
      container.appendChild(face);
    },
  },
  // ワールドマップの時計エリアと同じ文字盤を表示する。モーダルは開くたびに新しくSVGを作って
  // 一度だけ位相を合わせれば十分(継続的な再同期チェックは部屋セル内表示側だけで行う)
  clock: {
    render(container, o, roomLabel) {
      const row = document.createElement("div");
      row.className = "row";
      const l = document.createElement("span"); l.className = "label"; l.textContent = "ルーム";
      const v = document.createElement("span"); v.className = "value";
      v.textContent = roomLabel ? `${roomLabel} #${o.room}` : `Room ${o.room}`;
      row.append(l, v);
      container.appendChild(row);

      const face = document.createElement("div");
      face.className = "clock-face";
      face.innerHTML = CLOCK_FACE_SVG;
      container.appendChild(face);
      syncClockHands({ hour: face.querySelector(".hand.hour"), min: face.querySelector(".hand.min"),
                        sec: face.querySelector(".hand.sec") });
    },
  },
  // YouTubeエリアと同じく「押すまで通信・再生しない」原則。押したときだけbuildYouTubeEmbedで
  // iframeを差し込む。他で再生中のタイルがあれば止める(同時に鳴らせるのは1つだけ)
  youtube: {
    render(container, o, roomLabel) {
      const row = document.createElement("div");
      row.className = "row";
      const l = document.createElement("span"); l.className = "label"; l.textContent = "ルーム";
      const v = document.createElement("span"); v.className = "value";
      v.textContent = roomLabel ? `${roomLabel} #${o.room}` : `Room ${o.room}`;
      row.append(l, v);
      container.appendChild(row);

      const stage = document.createElement("div");
      stage.className = "status-yt-stage";
      const thumbImg = document.createElement("img");
      thumbImg.src = npcImageUrl(o);
      thumbImg.alt = "";
      const playBtn = document.createElement("button");
      playBtn.type = "button";
      playBtn.className = "status-yt-play";
      playBtn.textContent = "▶";
      playBtn.addEventListener("click", () => {
        stopAllPlayback();
        renderWorld(); // stopTilePlayback/stopRoomNpcPlayback自体は状態を倒すだけで見た目
                        // (▶やラベル)は次のrenderWorld()まで変わらないので、ここで即座に反映させる
        stage.replaceChildren(buildYouTubeEmbed(o.videoId, { autoplay: true }));
      });
      stage.append(thumbImg, playBtn);
      container.appendChild(stage);
    },
  },
};

function openCharaStatus(o, portrait, roomLabel) {
  const spec = CHARA_STATUS_KINDS[o.kind] || CHARA_STATUS_KINDS.basic;
  charaStatusName.textContent = o.name;
  charaStatusPortrait.hidden = !portrait;
  if (portrait) {
    charaStatusPortrait.classList.toggle("custom", portrait.custom);
    charaStatusPortrait.style.backgroundImage = portrait.custom ? `url(${portrait.url})` : "";
    charaStatusPortrait.style.backgroundPosition = portrait.custom ? "" : portrait.position;
  }
  charaStatusText.innerHTML = "";
  spec.render(charaStatusText, o, roomLabel);
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

const PEER_STATUS = { false: "接続できません", null: "接続中…", undefined: "接続中…" };

// マスを別のエリアに明け渡す前の後始末。再生中のiframeは隠すだけでは音が止まらないので破棄する
// (.tile.empty のCSSはimg/overlay/label/statusしか隠さない)
function resetTile(tile) {
  tile.key = null;
  tile.lastState = "";
  tile.status.hidden = true;
  tile.playBtn.hidden = tile.zoomBtn.hidden = true;
  tile.videoId = null;
  tile.areaName = null;
  tile.calendarKey = null;
  tile.browserUrl = null;
  tile.browserFrame.replaceChildren();
  tile.roomStateOverlay.hidden = true;
  stopTilePlayback(tile);
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
      tile.label.textContent = "このルーム";
      tile.status.hidden = true;
      tile.playBtn.hidden = tile.zoomBtn.hidden = true;
      renderRoomInto(tile, lastEntries, selfCharaUrl, null, visible);
      const stateLabel = ROOM_STATE_LABELS[roomState];
      tile.roomStateOverlay.hidden = !stateLabel;
      if (stateLabel) tile.roomStateText.textContent = stateLabel;
    } else if (slot.area.kind === "youtube") {
      renderYouTubeTile(tile, slot.area, focused);
    } else if (slot.area.kind === "clock") {
      renderClockTile(tile, slot.area, focused, visible);
    } else if (slot.area.kind === "calendar") {
      renderCalendarTile(tile, slot.area, focused);
    } else if (slot.area.kind === "browser") {
      renderBrowserTile(tile, slot.area, focused);
    } else if (slot.area.kind === "peer") {
      renderPeerTile(tile, slot.area, focused, visible);
    } else {
      // 知らない種別(設定を手で編集した場合など)。霧のマスにして何も壊さない
      resetTile(tile);
      setClass(tile.el, "tile empty");
    }
  });
  renderNowPlaying();
  roomViewEl.classList.toggle("showing-self", focus === "self");
  backToMapBtn.hidden = !(areas.length > 0 && focusedKey !== null);
}

// 管理者が置いた掛け時計。出すのは見ている人の手元の時刻(サーバーの時刻ではない)。
// 針はCSSアニメーションが回すので、ここでやるのは位相合わせだけ。毎秒動くJSは存在しない
function renderClockTile(tile, area, focused, visible) {
  setClass(tile.el, `tile clock${focused}`);
  tile.label.textContent = area.name;
  tile.status.hidden = true;
  tile.playBtn.hidden = tile.zoomBtn.hidden = true;
  // 隠れている間は触らない。display:none はCSSアニメーションを破棄するので、ここで位相を
  // 書いても見えた瞬間に「書いた時刻」のまま復活して、ずれた時計が動き続けることになる。
  // 見えたときに「いま針が指している時刻」を確かめて、違っていれば直す
  if (visible && clockNeedsSync(tile.hands)) syncClockHands(tile.hands);
}

// 針が指している時刻と実時刻のずれをこれ以上許さない値(秒)。チクタクの1目盛りより小さくとる
const CLOCK_TOLERANCE_SEC = 0.5;

// いま実際に表示されているべき位相(秒)。sec/min/hour それぞれの周期に対する経過秒
function clockPhases() {
  const n = new Date();
  const sec = n.getSeconds() + n.getMilliseconds() / 1000;
  const min = n.getMinutes() * 60 + sec;
  return { sec, min, hour: (n.getHours() % 12) * 3600 + min };
}

// 針が本当に指している位相(秒)。Animation.currentTime は delay を含まないので、
// 実際に描かれている位置は currentTime から delay を引いた値になる。
// null ならアニメーションが生成されていない(または破棄された)
function shownPhase(hand, period) {
  const anim = hand.getAnimations()[0];
  if (!anim || anim.currentTime === null) return null;
  const local = (anim.currentTime - anim.effect.getTiming().delay) / 1000;
  return ((local % period) + period) % period;
}

// 「同期してから何秒経ったか」を自分で数える方式にすると、OSスリープやタブの凍結で
// アニメーションだけが止まった場合を取りこぼす。針が指している位置を直接読めば
// 原因によらず検出でき、何かの拍子にずれても次の描画で自力で直る。
// プロパティを読むだけなのでスタイルの再計算は走らない
function clockNeedsSync(hands) {
  const shown = shownPhase(hands.sec, 60);
  if (shown === null) return true;
  const diff = Math.abs(shown - clockPhases().sec);
  return Math.min(diff, 60 - diff) > CLOCK_TOLERANCE_SEC;
}

// 位相合わせ。動かすのは animation-delay だけにして、CSS を唯一の真実に保つ
// (Animation.currentTime を直接書くと、インラインの delay が残っている限り
//  次のスタイル再計算で元に戻されてしまう)。
// 描かれる位置は currentTime - delay なので、delay をその差に置けば狙った位相になる。
// まだアニメーションが無いときは経過0とみなす(= 負のdelayが初期位相になる)。
// キャラの揺れ(bob)を animationDelay でずらしているのと同じ仕組み
function syncClockHands(hands) {
  for (const [name, phase] of Object.entries(clockPhases())) {
    const hand = hands[name];
    const anim = hand.getAnimations()[0];
    const currentTime = anim && anim.currentTime !== null ? anim.currentTime : 0;
    hand.style.animationDelay = `${(currentTime - phase * 1000) / 1000}s`;
  }
}

// 管理者が置いたカレンダー。出すのは見ている人の手元の日付(サーバーでもタイムゾーン指定でもない)。
// 時計と違って連続アニメーションが無いので、日付キーが変わったときだけ書き直せば足りる
function renderCalendarTile(tile, area, focused) {
  setClass(tile.el, `tile calendar${focused}`);
  tile.label.textContent = area.name;
  tile.status.hidden = true;
  tile.playBtn.hidden = tile.zoomBtn.hidden = true;
  const today = new Date();
  const key = calendarDateKey(today);
  if (tile.calendarKey !== key) {
    tile.calendarKey = key;
    tile.calendarFace.innerHTML = buildCalendarFaceHTML(today);
  }
}

// 管理者が置いた任意ページのiframe。YouTubeと違い▶待ちはせず、置かれた瞬間に全員の画面で
// 読み込まれる(OBSのブラウザソースと同じ「常時表示のアンビエントウィジェット」という位置づけ)
function renderBrowserTile(tile, area, focused) {
  setClass(tile.el, `tile browser${focused}`);
  tile.label.textContent = area.name;
  tile.status.hidden = true;
  tile.playBtn.hidden = tile.zoomBtn.hidden = true;
  tile.browserFrame.setAttribute("aria-hidden", focused ? "false" : "true");
  // URLが変わっていなければ触らない。ここを毎ポーリング(2秒毎)で作り直すと無限リロードになる
  if (tile.browserUrl === area.url) return;
  tile.browserUrl = area.url;
  const iframe = document.createElement("iframe");
  iframe.src = area.url;
  iframe.title = area.name;
  iframe.referrerPolicy = "no-referrer";
  // allow-scripts+allow-same-originの組み合わせは「同一オリジンをsandbox化した場合」だけ
  // sandbox回避に使われる既知の抜け穴になる。ここは通常他ドメインのiframeなので安全な組み合わせだが、
  // 管理者が自分自身のもくもくサーバーのURLを指定した場合はこの前提が崩れ、埋め込んだページから
  // 親ウィンドウのlocalStorage(管理者合言葉を含む)を読めてしまいうる。ただしこれは管理者本人が
  // 自分のURLを自分に埋め込む自傷的なケースに限られ、第三者による権限昇格経路にはならない。
  // allow-top-navigation系は意図的に与えない(タブごと乗っ取る遷移を防ぐ)
  iframe.sandbox = "allow-scripts allow-same-origin allow-forms allow-popups";
  tile.browserFrame.replaceChildren(iframe);
}

// つながった相手のもくもくルーム。中身は自分のルームと同じ9部屋なので renderRoomInto を使い回す
function renderPeerTile(tile, area, focused, visible) {
  setTileImage(tile, area, area.roomImageVersion);
  setClass(tile.el, `tile peer${area.ok === false ? " offline" : ""}${focused}`);
  tile.label.textContent = area.ok === true ? `${area.name} (${(area.board || []).length}人)` : area.name;
  tile.status.hidden = area.ok === true;
  tile.status.textContent = PEER_STATUS[area.ok] || "";
  tile.playBtn.hidden = tile.zoomBtn.hidden = true;
  renderRoomInto(tile, area.board, peerCharaUrl(area.id), area.name, visible);
}

// 管理者が置いた動画1本のマス。再生前はサムネと▶だけで、iframeはまだ存在しない
function renderYouTubeTile(tile, area, focused) {
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
}

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

function toggleTileFocus(tile) {
  focusedKey = focusedKey === tile.key ? null : tile.key;
  renderWorld();
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

function renderBoard(entries) {
  lastEntries = entries;
  renderWorld();
  updateMyStatus();
  // 自分のルームの行に、つながった相手ルームの行を続ける
  const rows = [
    ...entries.map(e => ({ e, room: `Room ${e.room}`, local: true })),
    ...peerAreas().flatMap(p => (p.board || []).map(e => ({ e, room: `${p.name} #${e.room}`, local: false }))),
  ];
  if (rows.length === 0) {
    entriesEl.innerHTML = `<div class="empty">まだ誰ももくもくしていません</div>`;
    return;
  }
  entriesEl.innerHTML = "";
  rows.forEach(({ e, room, local }) => {
    const div = document.createElement("div");
    div.className = local ? "entry" : "entry remote";
    const when = `${esc(e.start)}〜${esc(e.end || "?")}`;
    div.innerHTML = `<span class="room">${esc(room)}</span><span class="who">${esc(e.name)}</span><span class="when">${when}</span><span class="what">${esc(e.task)}</span>`;
    // 相手サーバーの参加者は操作できないので強制退出ボタンは出さない。
    // NPCの片付けは強制退出とは別のライフサイクル(NPC管理パネル)で行うのでここには出さない
    if (local && isAdmin && e.id !== clientId && !e.npc) {
      const kickBtn = document.createElement("button");
      kickBtn.type = "button";
      kickBtn.className = "kick";
      kickBtn.textContent = "強制退出";
      kickBtn.addEventListener("click", () => kickUser(e.id, e.name));
      div.appendChild(kickBtn);
    }
    entriesEl.appendChild(div);
  });
}

// 自分のチャットとピアのチャットを1本の時系列にまとめる
function mergedMessages() {
  const all = localMessages.map(m => ({ ...m, ts: msgTs(m), from: null }));
  // peerIdは添付画像を /peer-message-image/<peerId>/... 経由で引くために使う
  peerAreas().forEach(p => (p.messages || []).forEach(m => all.push({ ...m, ts: msgTs(m), from: p.name, peerId: p.id })));
  return all.sort((a, b) => a.ts - b.ts);
}

// tsを持たない旧版のピア向けフォールバック。timeのHH:MMを今日の時刻として解釈する
function msgTs(m) {
  if (typeof m.ts === "number") return m.ts;
  const hhmm = String(m.time || "").match(/(\d{1,2}):(\d{2})/);
  if (!hhmm) return 0;
  const d = new Date();
  d.setHours(+hhmm[1], +hhmm[2], 0, 0);
  return d.getTime() / 1000;
}

// ▶と拡大ボタンは自前のハンドラでstopPropagationしているので、ここには上がってこない
worldMapEl.addEventListener("click", e => {
  if (areas.length === 0) return; // エリアなしのときは常に自分のルームの全画面
  const tile = tiles.find(t => t.el === e.target.closest(".tile"));
  if (!tile || !tile.key || focusedKey === tile.key) return;
  focusedKey = tile.key;
  renderWorld();
});

nowPlayingStopBtn.addEventListener("click", () => {
  stopAllPlayback();
  renderWorld();
});

nowPlayingGoBtn.addEventListener("click", () => {
  const playing = tiles.find(t => t.playing) || tiles.find(t => t.playingNpcId);
  if (playing) { focusedKey = playing.key; renderWorld(); }
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

// 入室状態に応じてフォームを切替:
//   入室前     → 入室フォームのみ(チャット不可)
//   入室中     → ステータス+編集/送信/退室ボタン+チャット
//   編集モード → 入室フォーム(ボタンは「更新」)。チャットは編集を終えるまで不可
function updateMyStatus() {
  const mine = lastEntries.find(e => e.id === clientId);
  if (mine) {
    const until = mine.end ? `〜${mine.end}` : "〜";
    myStatusEl.textContent = `🟢 ${mine.name}: ルーム${mine.room}でもくもく中(${mine.start}${until}): ${mine.task}`;
    viewOnlyRow.style.display = "none";
    joinRow.style.display = editing ? "flex" : "none";
    statusRow.style.display = editing ? "none" : "flex";
    joinBtn.textContent = "更新";
    cancelEditBtn.style.display = editing ? "inline-block" : "none";
  } else {
    editing = false;
    viewOnlyRow.style.display = receptionOpen ? "none" : "flex";
    joinRow.style.display = receptionOpen ? "flex" : "none";
    statusRow.style.display = "none";
    joinBtn.textContent = "入室";
    cancelEditBtn.style.display = "none";
  }
}

// 相手ルームから中継されてきた文字列も必ずここを通す。型が文字列とは限らないので String() で受ける
function esc(s) {
  return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

// 本文中のURLをテキストノードと<a>要素に分けてelに追加する。innerHTML文字列に組み込むのではなく
// DOM要素として組み立てるので、esc()を通さなくてもXSSの心配がない。
// 戻り値: 本文中で最初に見つかったYouTube動画ID(埋め込み用)。無ければnull
function appendLinkedText(el, text) {
  // 日本語の文中にスペース無しで続く場合に備え、CJK文字・全角記号・閉じ括弧はURLに含めない
  // (生のURLにこれらの文字が現れることは実質無いため、境界として扱って安全)
  const URL_RE = /https?:\/\/[^\s)\]}\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]+/g;
  let lastIndex = 0, match, videoId = null;
  while ((match = URL_RE.exec(text))) {
    if (match.index > lastIndex) el.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
    // 文末の句読点・閉じ括弧はURLに含めない(「〜です(https://...)。」のような文脈への対応)
    let url = match[0];
    const trail = url.match(/[)\]}.,!?、。」』]+$/);
    if (trail) url = url.slice(0, -trail[0].length);
    const a = document.createElement("a");
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = url;
    el.appendChild(a);
    if (trail) el.appendChild(document.createTextNode(trail[0]));
    if (!videoId) videoId = extractYouTubeId(url);
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) el.appendChild(document.createTextNode(text.slice(lastIndex)));
  return videoId;
}

// YouTubeの各種URL形式(watch?v=, youtu.be/, shorts/, embed/)から11文字の動画IDを取り出す。
// 該当しなければnull(埋め込みなし、リンクだけになる)
function extractYouTubeId(url) {
  let u;
  try { u = new URL(url); } catch { return null; }
  const host = u.hostname.replace(/^(www\.|m\.)/, "");
  const idOk = id => /^[\w-]{11}$/.test(id) ? id : null;
  if (host === "youtu.be") return idOk(u.pathname.slice(1));
  if (host === "youtube.com" || host === "youtube-nocookie.com") {
    if (u.pathname === "/watch") return idOk(u.searchParams.get("v") || "");
    const m = u.pathname.match(/^\/(?:shorts|embed)\/([\w-]{11})/);
    if (m) return idOk(m[1]);
  }
  return null;
}

// youtube-nocookie.comを使うのは、埋め込み再生に伴うトラッキング/Cookieを減らすため。
// autoplayはYouTubeルームの▶から呼ぶときだけ立てる(チャットの埋め込みは勝手に鳴らさない)。
// playsinlineが無いとiOSが強制的に全画面に飛ばすので、マス内再生が成立しなくなる
function buildYouTubeEmbed(id, { autoplay = false } = {}) {
  const wrap = document.createElement("div");
  wrap.className = "yt-embed";
  const iframe = document.createElement("iframe");
  iframe.src = `https://www.youtube-nocookie.com/embed/${id}${autoplay ? "?autoplay=1&playsinline=1" : ""}`;
  iframe.loading = "lazy";
  iframe.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share";
  iframe.allowFullscreen = true;
  iframe.referrerPolicy = "strict-origin-when-cross-origin";
  wrap.appendChild(iframe);
  return wrap;
}

// チャット添付画像。ローカルは自サーバー、ピア由来(m.fromあり)は中継エンドポイント経由で取得する。
// クリックで原寸を別タブに開けるよう<a>でラップする
function buildMsgImage(m) {
  const src = m.from
    ? `/peer-message-image/${encodeURIComponent(m.peerId)}/${encodeURIComponent(m.image)}.webp`
    : `/message-image/${encodeURIComponent(m.image)}.webp`;
  const link = document.createElement("a");
  link.href = src;
  link.target = "_blank";
  link.rel = "noopener";
  const img = document.createElement("img");
  img.className = "image";
  img.src = src;
  img.loading = "lazy";
  img.alt = "";
  link.appendChild(img);
  return link;
}

function nowHHMM() {
  return new Date().toTimeString().slice(0, 5);
}

// 選択された画像を最大256pxに縮小してPNGのデータURLにする(画像でないファイルはthrow)
async function fileToDataUrl(file) {
  const bmp = await createImageBitmap(file);
  const MAX = 256;
  const scale = Math.min(1, MAX / Math.max(bmp.width, bmp.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(bmp.width * scale));
  canvas.height = Math.max(1, Math.round(bmp.height * scale));
  canvas.getContext("2d").drawImage(bmp, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/png");
}

// チャット添付用。最大1600pxに縮小し、WebP品質50でエンコードする(画像でないファイルはthrow)
async function fileToWebpDataUrl(file) {
  const bmp = await createImageBitmap(file);
  const MAX = 1600;
  const scale = Math.min(1, MAX / Math.max(bmp.width, bmp.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(bmp.width * scale));
  canvas.height = Math.max(1, Math.round(bmp.height * scale));
  canvas.getContext("2d").drawImage(bmp, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/webp", 0.5);
}

// 書き込み系APIの共通処理。サーバーがvery easyモードのときは401が返るので、
// そこで初めて合言葉を聞いてlocalStorageに保存し再送する(noneモードでは一切聞かない)。
// キャンセルまたは規定回数失敗ならnullを返す(呼び出し元は中断する)
async function postJson(url, body) {
  for (let attempt = 0; attempt < 3; attempt++) {
    const passphrase = localStorage.getItem("mokumoku-passphrase") || "";
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(passphrase ? { ...body, passphrase } : body),
    });
    if (res.status !== 401) return res.json();
    localStorage.removeItem("mokumoku-passphrase");
    const input = (prompt(passphrase ? "合言葉が違います。もう一度入力してください" : "合言葉を入力してください") || "").trim();
    if (!input) return null;
    localStorage.setItem("mokumoku-passphrase", input);
  }
  localStorage.removeItem("mokumoku-passphrase");
  alert("合言葉が違います");
  return null;
}

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
    discordStatusEl.className = status.discord;
  }
  if (typeof status.roomImageVersion === "number") {
    scheduleRoomImageRefresh(status.roomImageVersion);
  }
  if (typeof status.roomState === "string" && status.roomState !== roomState) {
    roomState = status.roomState;
    renderWorld();
  }
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

// 今保持している合言葉が管理者合言葉かどうかをサーバーに確認する(ボタン表示の判定用)
async function checkAdmin() {
  const passphrase = localStorage.getItem("mokumoku-passphrase") || "";
  if (!passphrase) {
    isAdmin = false;
  } else {
    try {
      const res = await fetch("/admin/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ passphrase }),
      });
      const data = await res.json();
      isAdmin = !!data.isAdmin;
    } catch {
      isAdmin = false;
    }
  }
  syncAdminButtons();
}

async function kickUser(id, name) {
  if (!confirm(`${name} を強制退出させますか？`)) return;
  const passphrase = localStorage.getItem("mokumoku-passphrase") || "";
  try {
    const res = await fetch("/board/kick", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, passphrase, actorId: clientId }),
    });
    if (!res.ok) { alert("強制退出に失敗しました"); return; }
  } catch {
    alert("強制退出に失敗しました");
    return;
  }
  await poll();
}

// isAdminが変化した瞬間だけボタン(と開いていればパネル)を除去/追加する。
// renderBoardのkickボタンと違い、2秒ごとのpollで作り直すとパネルの開閉状態が消えてしまうため、
// 「変化があったときだけ」DOMを触る設計にする
function syncAdminButtons() {
  if (isAdmin === prevIsAdmin) return;
  prevIsAdmin = isAdmin;
  const existingBar = document.getElementById("adminBar");
  if (isAdmin && !existingBar) {
    const bar = document.createElement("div");
    bar.id = "adminBar";
    bar.append(
      adminButton("roomImageBtn", "部屋画像を変更", toggleRoomImagePanel),
      adminButton("roomStateBtn", "ルームの状態", toggleRoomStatePanel),
      adminButton("worldBtn", "ワールド設定", toggleWorldPanel),
      adminButton("npcBtn", "NPC管理", toggleNpcPanel),
    );
    roomViewEl.appendChild(bar);
  } else if (!isAdmin) {
    existingBar?.remove();
    document.getElementById("roomImagePanel")?.remove();
    document.getElementById("roomStatePanel")?.remove();
    document.getElementById("worldPanel")?.remove();
    document.getElementById("npcPanel")?.remove();
  }
}

function adminButton(id, label, onClick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.id = id;
  btn.textContent = label;
  btn.addEventListener("click", onClick);
  return btn;
}

async function toggleRoomImagePanel() {
  const existingPanel = document.getElementById("roomImagePanel");
  if (existingPanel) { existingPanel.remove(); return; }
  const passphrase = localStorage.getItem("mokumoku-passphrase") || "";
  let data;
  try {
    const res = await fetch("/admin/room-images", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passphrase }),
    });
    if (!res.ok) { alert("画像一覧の取得に失敗しました"); return; }
    data = await res.json();
  } catch {
    alert("画像一覧の取得に失敗しました");
    return;
  }
  const panel = document.createElement("div");
  panel.id = "roomImagePanel";
  (data.images || []).forEach(name => {
    const img = document.createElement("img");
    img.src = `/room-image-preview/${encodeURIComponent(name)}`;
    img.alt = name;
    img.title = name;
    if (name === data.current) img.classList.add("selected");
    img.addEventListener("click", () => applyRoomImage(name));
    panel.appendChild(img);
  });
  roomViewEl.appendChild(panel);
}

async function applyRoomImage(name) {
  const passphrase = localStorage.getItem("mokumoku-passphrase") || "";
  let data;
  try {
    const res = await fetch("/admin/room-image", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passphrase, file: name, actorId: clientId }),
    });
    if (!res.ok) { alert("部屋画像の変更に失敗しました"); return; }
    data = await res.json();
  } catch {
    alert("部屋画像の変更に失敗しました");
    return;
  }
  document.getElementById("roomImagePanel")?.remove();
  // 操作した本人はジッター待ちせず即時反映。以後のpollで同じバージョンを受け取っても
  // scheduleRoomImageRefreshが「既に反映済み」と判定して再取得しないよう基準値も更新する
  roomImageVersion = data.version;
  pendingImageVersion = null;
  selfRoomImageSrc = `/room-image.webp?v=${data.version}`;
  renderWorld();
}

const ROOM_STATE_OPTIONS = [
  { value: "normal", label: "通常" },
  { value: "preparing", label: "準備中" },
  { value: "closed", label: "Closed" },
];

// 現在値はpollで既に持っている(roomState)ので、画像一覧と違いサーバーへの問い合わせは不要
function toggleRoomStatePanel() {
  const existingPanel = document.getElementById("roomStatePanel");
  if (existingPanel) { existingPanel.remove(); return; }
  const panel = document.createElement("div");
  panel.id = "roomStatePanel";
  ROOM_STATE_OPTIONS.forEach(({ value, label }) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = label;
    if (value === roomState) btn.classList.add("selected");
    btn.addEventListener("click", () => applyRoomState(value));
    panel.appendChild(btn);
  });
  roomViewEl.appendChild(panel);
}

async function applyRoomState(state) {
  const passphrase = localStorage.getItem("mokumoku-passphrase") || "";
  let data;
  try {
    const res = await fetch("/admin/room-state", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passphrase, state, actorId: clientId }),
    });
    if (!res.ok) { alert("ルームの状態の変更に失敗しました"); return; }
    data = await res.json();
  } catch {
    alert("ルームの状態の変更に失敗しました");
    return;
  }
  document.getElementById("roomStatePanel")?.remove();
  roomState = data.state;
  renderWorld();
}

const AREA_ERRORS = {
  "invalid url": "URLの形式が正しくありません(https://から始まる有効なURLを入力してください)",
  "invalid video": "YouTubeの動画URLとして読み取れませんでした",
  "video unavailable": "その動画の情報を取得できませんでした(限定公開・削除済みかもしれません)",
  "already connected": "そのルームとは既につながっています",
  "area limit reached": "マップに置けるのは8マスまでです",
  "not found": "そのエリアは見つかりませんでした",
  "admin required": "管理者合言葉が必要です",
};

async function toggleWorldPanel() {
  const existing = document.getElementById("worldPanel");
  if (existing) { existing.remove(); return; }
  const passphrase = localStorage.getItem("mokumoku-passphrase") || "";
  let data;
  try {
    const res = await fetch("/admin/areas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passphrase }),
    });
    if (!res.ok) { alert("ワールド設定の取得に失敗しました"); return; }
    data = await res.json();
  } catch {
    alert("ワールド設定の取得に失敗しました");
    return;
  }
  const panel = document.createElement("div");
  panel.id = "worldPanel";
  const list = data.areas || [];
  if (list.length === 0) {
    const empty = document.createElement("div");
    empty.className = "peer-empty";
    empty.textContent = "マップにはまだ何も置かれていません";
    panel.appendChild(empty);
  }
  list.forEach(a => panel.appendChild(buildAreaRow(a)));
  panel.appendChild(buildAreaAddForm());
  roomViewEl.appendChild(panel);
}

// エリアの種別ごとの見せ方。増えるたびに三項演算子を継ぎ足すと読めなくなるので表にまとめる。
// needsUrl は「置くのにURLを要る種別か」で、時計のように外から取るものが無い種別は false
const AREA_KINDS = {
  peer: {
    label: "もくもくルーム", needsUrl: true, addLabel: "つなぐ", delLabel: "解除",
    confirm: "この接続を解除しますか？", urlHint: "相手ルームのURL (https://...)",
    nameHint: "表示名 (任意)", missingUrl: "相手ルームのURLを入力してください",
    title: a => a.url || "",
    text: a => a.type === "fork" ? `${a.name} (Redis版)` : a.name,
  },
  youtube: {
    label: "YouTubeルーム", needsUrl: true, addLabel: "置く", delLabel: "片付ける",
    confirm: "このYouTubeルームを片付けますか？", urlHint: "YouTubeの動画URL",
    nameHint: "表示名 (任意/未指定なら動画タイトル)", missingUrl: "YouTubeの動画URLを入力してください",
    title: a => `https://youtu.be/${a.videoId}`,
    text: a => `📺 ${a.name}`,
  },
  clock: {
    label: "時計", needsUrl: false, addLabel: "置く", delLabel: "片付ける",
    confirm: "この時計を片付けますか？", urlHint: "",
    nameHint: "表示名 (任意/未指定なら「時計」)", missingUrl: "",
    title: () => "見ている人の手元の時刻を表示します",
    text: a => `🕐 ${a.name}`,
  },
  calendar: {
    label: "カレンダー", needsUrl: false, addLabel: "置く", delLabel: "片付ける",
    confirm: "このカレンダーを片付けますか？", urlHint: "",
    nameHint: "表示名 (任意/未指定なら「カレンダー」)", missingUrl: "",
    title: () => "見ている人の手元の日付を表示します",
    text: a => `📅 ${a.name}`,
  },
  browser: {
    label: "ブラウザ", needsUrl: true, addLabel: "置く", delLabel: "片付ける",
    confirm: "このブラウザを片付けますか？", urlHint: "表示したいページのURL",
    nameHint: "表示名 (任意/未指定ならホスト名)", missingUrl: "表示したいページのURLを入力してください",
    title: a => a.url || "",
    text: a => `🌐 ${a.name}`,
  },
};

const areaKind = kind => AREA_KINDS[kind] || AREA_KINDS.peer;

// 置いてあるエリア1件ぶんの行。YouTubeルームだけは動画の差し替え欄も持つ
function buildAreaRow(a) {
  const spec = areaKind(a.kind);
  const row = document.createElement("div");
  row.className = "peer-row";
  const info = document.createElement("span");
  info.className = "peer-info";
  info.textContent = spec.text(a);
  info.title = spec.title(a);
  const del = document.createElement("button");
  del.type = "button";
  del.className = "peer-del";
  del.textContent = spec.delLabel;
  del.addEventListener("click", () => changeArea({ action: "remove", id: a.id, kind: a.kind }));
  row.append(info, del);
  // 差し替えられるのは今のところYouTubeの動画だけ
  if (a.kind !== "youtube") return row;
  const swapInput = document.createElement("input");
  swapInput.type = "text";
  swapInput.placeholder = "別の動画URLに差し替え";
  const swap = () => changeArea({ action: "update", id: a.id, kind: "youtube", url: swapInput.value.trim() });
  swapInput.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); swap(); }
  });
  const swapBtn = document.createElement("button");
  swapBtn.type = "button";
  swapBtn.textContent = "変更";
  swapBtn.addEventListener("click", swap);
  const sub = document.createElement("div");
  sub.className = "peer-swap";
  sub.append(swapInput, swapBtn);
  row.appendChild(sub);
  return row;
}

// 新しくエリアを置くフォーム。種別で入力欄の意味が変わるので、選択に応じて出し分ける
function buildAreaAddForm() {
  const kindSelect = document.createElement("select");
  kindSelect.innerHTML = Object.entries(AREA_KINDS)
    .map(([k, spec]) => `<option value="${k}">${spec.label}</option>`).join("");
  const urlInput = document.createElement("input");
  urlInput.type = "text";
  const nameInput = document.createElement("input");
  nameInput.type = "text";
  // fork型はelm200版(FastAPI+Redis)向けの読み替えアダプタを使う。向こうのRedis消費を抑えるため
  // 巡回間隔も別扱いになる(config/settings.jsonのworld.fork_poll_interval_sec)
  const typeSelect = document.createElement("select");
  typeSelect.innerHTML = `<option value="native">通常</option><option value="fork">Redis版</option>`;
  const addBtn = document.createElement("button");
  addBtn.type = "button";
  const syncKind = () => {
    const spec = areaKind(kindSelect.value);
    // URLが要らない種別(時計など)ではURL欄ごと消す。空欄を残すと何を入れる欄か分からない
    urlInput.hidden = !spec.needsUrl;
    urlInput.placeholder = spec.urlHint;
    nameInput.placeholder = spec.nameHint;
    // 通常/Redis版の区別があるのは相手ルームにつなぐときだけ
    typeSelect.hidden = kindSelect.value !== "peer";
    addBtn.textContent = spec.addLabel;
  };
  kindSelect.addEventListener("change", syncKind);
  syncKind();
  const submit = () => changeArea({
    action: "add", kind: kindSelect.value, url: urlInput.value.trim(),
    name: nameInput.value.trim(), type: typeSelect.value,
  });
  [urlInput, nameInput].forEach(el => el.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); submit(); }
  }));
  addBtn.addEventListener("click", submit);
  const add = document.createElement("div");
  add.className = "peer-add";
  add.append(kindSelect, urlInput, nameInput, typeSelect, addBtn);
  return add;
}

async function changeArea(body) {
  const spec = areaKind(body.kind);
  // URLが要らない種別(時計など)はここで弾かない
  if (body.action !== "remove" && spec.needsUrl && !body.url) {
    alert(spec.missingUrl);
    return;
  }
  if (body.action === "remove" && !confirm(spec.confirm)) return;
  const passphrase = localStorage.getItem("mokumoku-passphrase") || "";
  try {
    const res = await fetch("/admin/area", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...body, passphrase, actorId: clientId }),
    });
    const data = await res.json();
    if (!res.ok) { alert(AREA_ERRORS[data.error] || "操作に失敗しました"); return; }
    // サムネは取れたがoEmbedが拒否した動画、またはX-Frame-Options/CSPが拒否と分かったページ。
    // 多くは埋め込み禁止で、マスには置けても表示・再生できない
    if (data.embeddable === false) {
      alert(body.kind === "browser"
        ? "このページは外部サイトへの埋め込みを許可していない可能性があります。\nマスには置きましたが、参加者の画面では表示できないかもしれません。"
        : "この動画は外部サイトへの埋め込みが許可されていない可能性があります。\nマスには置きましたが、参加者の画面で再生できないかもしれません。");
    }
  } catch {
    alert("操作に失敗しました");
    return;
  }
  document.getElementById("worldPanel")?.remove();
  await poll();
  toggleWorldPanel(); // 更新後の一覧を出し直す
}

// NPCの種別ごとの見せ方(AREA_KINDSと同じ思想)。needsTask/needsImageで入力欄の要否を出し分ける
const NPC_KINDS = {
  basic: {
    label: "基本NPC", addLabel: "入室させる", delLabel: "片付ける",
    confirm: "このNPCを片付けますか？",
    needsTask: true, needsImage: true, nameHint: "NPCの名前",
  },
  calendar: {
    label: "カレンダー", addLabel: "入室させる", delLabel: "片付ける",
    confirm: "このカレンダーNPCを片付けますか？",
    needsTask: false, needsImage: false, nameHint: "表示名 (任意/未指定なら「カレンダー」)",
  },
  clock: {
    label: "時計", addLabel: "入室させる", delLabel: "片付ける",
    confirm: "この時計NPCを片付けますか？",
    needsTask: false, needsImage: false, nameHint: "表示名 (任意/未指定なら「時計」)",
  },
  youtube: {
    label: "YouTube", addLabel: "入室させる", delLabel: "片付ける",
    confirm: "このYouTube NPCを片付けますか？",
    needsTask: false, needsImage: false, needsUrl: true,
    nameHint: "表示名 (任意/未指定なら動画タイトル)", urlHint: "YouTubeの動画URL",
  },
};

const NPC_ERRORS = {
  "name and task required": "名前とやることを入力してください",
  "invalid image": "画像として読み込めませんでした",
  "invalid kind": "不明な種別です",
  "not found": "そのNPCは見つかりませんでした",
  "admin required": "管理者合言葉が必要です",
  "invalid video": "YouTubeの動画URLとして読み取れませんでした",
  "video unavailable": "その動画の情報を取得できませんでした(限定公開・削除済みかもしれません)",
};

// NPCは実参加者と同じboardに乗っているので、追加フェッチせず既にpoll済みのlastEntriesから拾う
function toggleNpcPanel() {
  const existing = document.getElementById("npcPanel");
  if (existing) { existing.remove(); return; }
  const panel = document.createElement("div");
  panel.id = "npcPanel";
  const npcs = lastEntries.filter(e => e.npc);
  if (npcs.length === 0) {
    const empty = document.createElement("div");
    empty.className = "peer-empty";
    empty.textContent = "NPCはまだ配置されていません";
    panel.appendChild(empty);
  }
  npcs.forEach(e => panel.appendChild(buildNpcRow(e)));
  panel.appendChild(buildNpcAddForm());
  roomViewEl.appendChild(panel);
}

function buildNpcRow(e) {
  const spec = NPC_KINDS[e.kind] || NPC_KINDS.basic;
  const row = document.createElement("div");
  row.className = "peer-row";
  const info = document.createElement("span");
  info.className = "peer-info";
  info.textContent = e.task
    ? `🤖 ${e.name}(ルーム${e.room}): ${e.task}`
    : `🤖 ${e.name}(ルーム${e.room})`;
  const del = document.createElement("button");
  del.type = "button";
  del.className = "peer-del";
  del.textContent = spec.delLabel;
  del.addEventListener("click", () => changeNpc({ action: "remove", id: e.id, kind: e.kind }));
  row.append(info, del);
  return row;
}

// kindセレクトで入力欄の要否を出し分ける(buildAreaAddFormのsyncKind方式と同型)
function buildNpcAddForm() {
  const kindSelect = document.createElement("select");
  kindSelect.innerHTML = Object.entries(NPC_KINDS)
    .map(([k, spec]) => `<option value="${k}">${spec.label}</option>`).join("");
  const nameInput = document.createElement("input");
  nameInput.type = "text";
  const taskInput = document.createElement("input");
  taskInput.type = "text";
  taskInput.placeholder = "やること・セリフ";
  const urlInput = document.createElement("input");
  urlInput.type = "text";
  const imageInput = document.createElement("input");
  imageInput.type = "file";
  imageInput.accept = "image/*";
  const addBtn = document.createElement("button");
  addBtn.type = "button";
  const syncKind = () => {
    const spec = NPC_KINDS[kindSelect.value];
    nameInput.placeholder = spec.nameHint;
    taskInput.hidden = !spec.needsTask;
    imageInput.hidden = !spec.needsImage;
    urlInput.hidden = !spec.needsUrl;
    urlInput.placeholder = spec.urlHint || "";
    addBtn.textContent = spec.addLabel;
  };
  kindSelect.addEventListener("change", syncKind);
  syncKind();
  const submit = async () => {
    const spec = NPC_KINDS[kindSelect.value];
    const name = nameInput.value.trim();
    const task = taskInput.value.trim();
    const url = urlInput.value.trim();
    if (spec.needsTask && (!name || !task)) { alert("名前とやることを入力してください"); return; }
    if (spec.needsUrl && !url) { alert("YouTubeの動画URLを入力してください"); return; }
    let image = null;
    if (spec.needsImage && imageInput.files[0]) {
      try { image = await fileToDataUrl(imageInput.files[0]); }
      catch { alert("画像として読み込めませんでした"); return; }
    }
    changeNpc({ action: "add", kind: kindSelect.value, name, task, url, ...(image && { image }) });
  };
  [nameInput, taskInput, urlInput].forEach(el => el.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); submit(); }
  }));
  addBtn.addEventListener("click", submit);
  const add = document.createElement("div");
  add.className = "peer-add";
  add.append(kindSelect, nameInput, taskInput, urlInput, imageInput, addBtn);
  return add;
}

async function changeNpc(body) {
  const spec = NPC_KINDS[body.kind] || NPC_KINDS.basic;
  if (body.action === "remove" && !confirm(spec.confirm)) return;
  const passphrase = localStorage.getItem("mokumoku-passphrase") || "";
  let data;
  try {
    const res = await fetch("/admin/npc", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...body, passphrase, actorId: clientId }),
    });
    data = await res.json();
    if (!res.ok) { alert(NPC_ERRORS[data.error] || "操作に失敗しました"); return; }
    // サムネは取れたがoEmbedが拒否した動画(埋め込み禁止の可能性)。changeAreaと同じ扱い
    if (data.embeddable === false) {
      alert("この動画は外部サイトへの埋め込みが許可されていない可能性があります。\nマスには置きましたが、参加者の画面で再生できないかもしれません。");
    }
  } catch {
    alert("操作に失敗しました");
    return;
  }
  if (data.roomFull) { alert("満室です。NPCを入れる空き部屋がありません"); return; }
  document.getElementById("npcPanel")?.remove();
  await poll();
  toggleNpcPanel(); // 更新後の一覧を出し直す
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

taskEl.addEventListener("input", () => {
  if (taskEl.value && !startEl.value) startEl.value = nowHHMM();
});

// Enterで送信、Shift+Enterで改行(IME変換確定のEnterでは送信しない)
textEl.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    form.requestSubmit();
  }
});

// 入力に合わせて高さを自動調整
textEl.addEventListener("input", () => {
  textEl.style.height = "auto";
  textEl.style.height = Math.min(textEl.scrollHeight, 120) + "px";
});

// 送信待ちの添付画像(WebPデータURL)。1メッセージにつき1枚まで
let pendingImage = null;

function setPendingImage(dataUrl) {
  pendingImage = dataUrl;
  pendingImagePreview.src = dataUrl;
  pendingImageRow.style.display = "flex";
}

function clearPendingImage() {
  pendingImage = null;
  pendingImagePreview.src = "";
  pendingImageRow.style.display = "none";
  msgImageEl.value = "";
}

attachImageBtn.addEventListener("click", () => msgImageEl.click());

msgImageEl.addEventListener("change", async () => {
  const file = msgImageEl.files[0];
  if (!file) return;
  try {
    setPendingImage(await fileToWebpDataUrl(file));
  } catch {
    alert("画像として読み込めませんでした");
    msgImageEl.value = "";
  }
});

removePendingImageBtn.addEventListener("click", clearPendingImage);

// クリップボードに画像がある状態でチャット欄にCtrl+Vすると、そのまま添付扱いにする。
// 画像を含まないペースト(通常のテキスト貼り付け)は既定の動作のままにする
textEl.addEventListener("paste", async e => {
  const item = [...(e.clipboardData?.items || [])].find(i => i.kind === "file" && i.type.startsWith("image/"));
  if (!item) return;
  e.preventDefault();
  const file = item.getAsFile();
  if (!file) return;
  try {
    setPendingImage(await fileToWebpDataUrl(file));
  } catch {
    alert("画像として読み込めませんでした");
  }
});

form.addEventListener("submit", async e => {
  e.preventDefault();
  const name = nameEl.value.trim();
  const text = textEl.value.trim();
  if (!name || (!text && !pendingImage)) return;
  const result = await postJson("/messages", { name, text, ...(pendingImage && { image: pendingImage }) });
  if (!result) return;
  textEl.value = "";
  textEl.style.height = "auto";
  clearPendingImage();
  await poll();
});

joinBtn.addEventListener("click", async () => {
  const name = nameEl.value.trim();
  const task = taskEl.value.trim();
  if (!name) { alert("名前を入力してください"); nameEl.focus(); return; }
  if (!task) { alert("もくもくする内容を入力してください"); taskEl.focus(); return; }
  let image = null;
  if (charaEl.files[0]) {
    try {
      image = await fileToDataUrl(charaEl.files[0]);
    } catch {
      alert("画像として読み込めませんでした");
      charaEl.value = "";
      return;
    }
  }
  const result = await postJson("/board/join", { id: clientId, name, task, start: startEl.value, end: endEl.value, ...(image && { image }) });
  if (!result) return;
  if (result.roomFull) {
    alert("満室です。空きが出るまでお待ちください");
    return;
  }
  if (result.error) {
    alert("入室に失敗しました: " + result.error);
    return;
  }
  // 送信済みの画像はクリア(編集モードで再送しない=サーバー側で維持される)
  charaEl.value = "";
  recordRow.style.display = "none";
  const wasEditing = editing;
  editing = false;
  // 新規入室時は挨拶メッセージを規定値としてセット
  if (!wasEditing && !textEl.value) {
    textEl.value = `${task}でもくもくします`;
  }
  await poll();
  textEl.focus();
});

editBtn.addEventListener("click", () => {
  const mine = lastEntries.find(e => e.id === clientId);
  if (!mine) return;
  editing = true;
  nameEl.value = mine.name;
  taskEl.value = mine.task;
  startEl.value = mine.start;
  endEl.value = mine.end;
  updateMyStatus();
  taskEl.focus();
});

cancelEditBtn.addEventListener("click", () => {
  editing = false;
  charaEl.value = "";
  updateMyStatus();
});

// 入室フォームでEnterを押したら入室(IME変換確定は除く)
[nameEl, taskEl].forEach(el => el.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.isComposing) {
    e.preventDefault();
    joinBtn.click();
  }
}));

goReceptionBtn.addEventListener("click", () => {
  receptionOpen = true;
  updateMyStatus();
  nameEl.focus();
});

leaveBtn.addEventListener("click", async () => {
  if (!confirm("退室しますか？")) return;
  const result = await postJson("/board/leave", { id: clientId });
  if (!result) return;
  // 退室したら合言葉を覚えたままにしない。次回入室時に必ず聞き直すことで、
  // 同じブラウザでも管理者合言葉に切り替えて入り直せるようにする
  localStorage.removeItem("mokumoku-passphrase");
  receptionOpen = false;
  taskEl.value = "";
  startEl.value = "";
  endEl.value = "";
  if (result.record) {
    recordText.value = result.record;
    recordRow.style.display = "flex";
  }
  await poll();
});

copyBtn.addEventListener("click", async () => {
  recordText.select();
  let ok = false;
  // LAN経由のhttp(非セキュアコンテキスト)ではclipboard APIが使えないためexecCommandにフォールバック
  if (navigator.clipboard && window.isSecureContext) {
    try { await navigator.clipboard.writeText(recordText.value); ok = true; } catch {}
  }
  if (!ok) ok = document.execCommand("copy");
  copyBtn.textContent = ok ? "コピーしました" : "コピー失敗";
  setTimeout(() => { copyBtn.textContent = "コピー"; }, 1500);
});

closeRecordBtn.addEventListener("click", () => {
  recordRow.style.display = "none";
});

renderWorld(); // 初回pollを待たずに自分のルームを出す
poll();
setInterval(poll, 2000);
