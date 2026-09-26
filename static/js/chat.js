// チャット欄。自分のルームのチャットと、つながった相手ルームのチャットを1本の時系列で見せる
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
  const text = textEl.value.trim();
  if (!text && !pendingImage) return;
  const result = await postJson("/messages", { id: clientId, seat: seatToken(), text, ...(pendingImage && { image: pendingImage }) });
  if (!result) return;
  if (result.error === "not joined") { alert("入室してから発言してください"); return; }
  if (result.error === "not your seat") { alert(NOT_YOUR_SEAT_MESSAGE); return; }
  textEl.value = "";
  textEl.style.height = "auto";
  clearPendingImage();
  await poll();
});
