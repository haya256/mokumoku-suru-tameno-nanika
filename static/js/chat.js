// チャット欄。自分のルームのチャットと、つながった相手ルームのチャットを1本の時系列で見せる
// 発言ごとのDOM要素を取っておき、増えた分だけ足して消えた分だけ外す。
// 毎回すべて作り直すと、チャットに埋め込んだYouTubeが誰かの発言のたびに頭から再生し直しになり、
// 発言がたまるほど描き直しも重くなる
const msgEls = new Map(); // 発言のキー -> 要素
let msgElsForAdmin = false; // 取ってある要素が管理者向け(削除ボタンつき)かどうか

// 発言を見分けるキー。idを持たない旧版のピアの発言は、発信元・時刻・名前・本文で代用する
function msgKey(m) {
  const origin = m.from ? `p:${m.peerId}` : "l";
  return m.id ? `${origin}:${m.id}` : `${origin}:${m.ts}:${m.name}:${m.text}`;
}

function buildMsgEl(m) {
  const div = document.createElement("div");
  // m.from はピア由来のときだけ入る発信元ルーム名
  const from = m.from ? `<span class="from">${esc(m.from)}</span>` : "";
  const remote = m.from ? " remote" : "";
  if (m.system) {
    div.className = `msg system${remote}`;
    div.innerHTML = `<span class="stamp">${esc(m.time)}</span>${from}${esc(m.text)}`;
    return div;
  }
  div.className = `msg${remote}`;
  div.innerHTML = `<div class="meta">${from}<span>${esc(m.name)}</span> ${esc(m.time)}</div>`;
  // 管理者は自分のルームの発言を削除できる(相手ルームの発言は相手の管理者の領分)
  if (isAdmin && !m.from && m.id) {
    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "delete";
    delBtn.textContent = "削除";
    delBtn.addEventListener("click", () => deleteMessage(m.id, m.name));
    div.querySelector(".meta").appendChild(delBtn);
  }
  const textEl = document.createElement("div");
  textEl.className = "text";
  const videoId = appendLinkedText(textEl, String(m.text ?? ""));
  div.appendChild(textEl);
  if (videoId) div.appendChild(buildYouTubeEmbed(videoId));
  if (m.image) div.appendChild(buildMsgImage(m));
  return div;
}

function render(msgs) {
  // 管理者になった・外れたときは削除ボタンを出し直すので、そのときだけ全部作り直す
  if (msgElsForAdmin !== isAdmin) {
    msgElsForAdmin = isAdmin;
    msgEls.clear();
    messagesEl.innerHTML = "";
  }
  // 同じキーが重なったとき(idの無い発言で内容まで同じ場合)は通し番号で分ける
  const seen = new Map();
  const keyed = msgs.map(m => {
    const base = msgKey(m);
    const n = seen.get(base) || 0;
    seen.set(base, n + 1);
    return [n ? `${base}#${n}` : base, m];
  });
  // 消えた発言(管理者による削除、相手ルームのスナップショットから外れた古い発言)を外す
  const alive = new Set(keyed.map(([key]) => key));
  for (const [key, el] of msgEls) {
    if (!alive.has(key)) { el.remove(); msgEls.delete(key); }
  }
  // 並び順どおりに置く。すでにある要素は正しい位置にあれば触らない(動かすと埋め込みが読み込み直しになる)。
  // ピアの取得遅れで途中に入る発言は、その位置に差し込む
  let added = false;
  let cursor = messagesEl.firstChild;
  for (const [key, m] of keyed) {
    let el = msgEls.get(key);
    if (!el) {
      el = buildMsgEl(m);
      msgEls.set(key, el);
      added = true;
    }
    if (el === cursor) cursor = cursor.nextSibling;
    else messagesEl.insertBefore(el, cursor);
  }
  if (added) messagesEl.scrollTop = messagesEl.scrollHeight;
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

// 「＋」で添付メニューを開き、項目を選んだら対応するファイル選択を出す。
// メニューの外をクリックするかEscで閉じる
function setAttachMenuOpen(open) {
  attachMenu.hidden = !open;
  attachImageBtn.setAttribute("aria-expanded", String(open));
}

attachImageBtn.addEventListener("click", e => {
  e.stopPropagation();
  setAttachMenuOpen(attachMenu.hidden);
});

attachImageItem.addEventListener("click", () => {
  setAttachMenuOpen(false);
  msgImageEl.click();
});

document.addEventListener("click", e => {
  if (!attachMenu.hidden && !attachMenu.contains(e.target)) setAttachMenuOpen(false);
});

document.addEventListener("keydown", e => {
  if (e.key === "Escape" && !attachMenu.hidden) {
    setAttachMenuOpen(false);
    attachImageBtn.focus();
  }
});

msgImageEl.addEventListener("change", async () => {
  const file = msgImageEl.files[0];
  if (!file) return;
  try {
    setPendingImage(await fileToChatImageDataUrl(file));
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
    setPendingImage(await fileToChatImageDataUrl(file));
  } catch {
    alert("画像として読み込めませんでした");
  }
});

form.addEventListener("submit", async e => {
  e.preventDefault();
  const text = textEl.value.trim();
  if (!text && !pendingImage) return;
  const result = await postJson("/messages", { id: clientId, seat: seatToken(), text, ...(pendingImage && { image: pendingImage }) });
  if (!result) return;
  if (result.error === "not joined") { alert("入室してから発言してください"); return; }
  if (result.error === "not your seat") { alert(NOT_YOUR_SEAT_MESSAGE); return; }
  // 失敗したのに入力を消すと送れたように見えてしまうので、入力と添付は残したまま知らせる
  if (result.error === "text too long") { alert("コメントが長すぎます(2000文字まで)"); return; }
  if (result.error === "invalid image") { alert("画像を送れませんでした。別の画像で試してみてください"); return; }
  if (result.error) { alert("送信できませんでした"); return; }
  textEl.value = "";
  textEl.style.height = "auto";
  clearPendingImage();
  await poll();
});
