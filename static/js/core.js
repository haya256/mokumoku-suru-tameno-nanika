// 画面全体で共有するDOM参照・状態と、どこからでも使う小さな道具。最初に読み込まれる
const messagesEl = document.getElementById("messages");
const roomTitleEl = document.getElementById("roomTitle");
const entriesEl = document.getElementById("entries");
const othersHeadingEl = document.getElementById("othersHeading");
const othersEl = document.getElementById("others");
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
// kindごとの描き方は kinds/ を参照(peer はつながった相手ルーム、youtube は管理者が置いた動画のマス、など)
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
// 入室証: 入室したときにサーバーから受け取る、本人だけが知っている文字列。
// 入室後の発言・編集・退室はIDと一緒にこれを送って本人確認してもらう
const seatToken = () => localStorage.getItem("mokumoku-seat") || "";
const NOT_YOUR_SEAT_MESSAGE = "入室中の本人と確認できませんでした。管理者に強制退出してもらってから入り直してください";
const ROOM_COUNT = 9;
// 3×3マップの中央は自分のルーム固定。ピアのslot(0〜7)は周囲8マスに対応する
const SELF_INDEX = 4;
const SLOT_TO_INDEX = [0, 1, 2, 3, 5, 6, 7, 8];

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
