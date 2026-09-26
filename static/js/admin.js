// 管理者用の操作(強制退出・ルームの設定・ワールド設定・NPC管理)。
// 表示・操作の可否はサーバーが都度合言葉で判定する。ここはボタンとパネルの出し入れだけ
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
      adminButton("roomSettingsBtn", "ルームの設定", toggleRoomSettingsPanel),
      adminButton("worldBtn", "ワールド設定", toggleWorldPanel),
      adminButton("npcBtn", "NPC管理", toggleNpcPanel),
    );
    roomViewEl.appendChild(bar);
  } else if (!isAdmin) {
    existingBar?.remove();
    document.getElementById("roomSettingsPanel")?.remove();
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

const ROOM_STATE_OPTIONS = [
  { value: "normal", label: "通常" },
  { value: "preparing", label: "準備中" },
  { value: "closed", label: "Closed" },
];

// ルームの設定: タイトル・参加者合言葉・状態・部屋画像をまとめたパネル。
// 状態とタイトルの現在値はpollで既に持っているので、問い合わせが要るのは画像一覧と参加者合言葉だけ
async function toggleRoomSettingsPanel() {
  const existingPanel = document.getElementById("roomSettingsPanel");
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
  panel.id = "roomSettingsPanel";
  panel.append(
    roomSettingsSection("タイトル", buildRoomTextForm(roomTitleEl.textContent, 40, applyRoomTitle)),
    roomSettingsSection("参加者合言葉", buildRoomTextForm(data.passphrase || "", 64, applyRoomPassphrase)),
    roomSettingsSection("状態", ...ROOM_STATE_OPTIONS.map(({ value, label }) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "room-state-btn";
      btn.textContent = label;
      if (value === roomState) btn.classList.add("selected");
      btn.addEventListener("click", () => applyRoomState(value));
      return btn;
    })),
    roomSettingsSection("部屋画像", ...(data.images || []).map(name => {
      const img = document.createElement("img");
      img.src = `/room-image-preview/${encodeURIComponent(name)}`;
      img.alt = name;
      img.title = name;
      if (name === data.current) img.classList.add("selected");
      img.addEventListener("click", () => applyRoomImage(name));
      return img;
    })),
  );
  roomViewEl.appendChild(panel);
}

function roomSettingsSection(heading, ...items) {
  const section = document.createElement("div");
  section.className = "room-settings-section";
  const h = document.createElement("div");
  h.className = "room-settings-heading";
  h.textContent = heading;
  const body = document.createElement("div");
  body.className = "room-settings-items";
  body.append(...items);
  section.append(h, body);
  return section;
}

// 入力欄+「変更」ボタンの1行フォーム(タイトル・参加者合言葉で共用)
function buildRoomTextForm(value, maxLength, onApply) {
  const input = document.createElement("input");
  input.type = "text";
  input.maxLength = maxLength;
  input.value = value;
  input.autocomplete = "off";
  const apply = () => onApply(input.value.trim());
  input.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); apply(); }
  });
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = "変更";
  btn.addEventListener("click", apply);
  const wrap = document.createElement("div");
  wrap.className = "room-title-form";
  wrap.append(input, btn);
  return wrap;
}

async function applyRoomTitle(title) {
  if (!title) { alert("タイトルを入力してください"); return; }
  const passphrase = localStorage.getItem("mokumoku-passphrase") || "";
  let data;
  try {
    const res = await fetch("/admin/room-title", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passphrase, title, actorId: clientId }),
    });
    if (!res.ok) { alert("タイトルの変更に失敗しました"); return; }
    data = await res.json();
  } catch {
    alert("タイトルの変更に失敗しました");
    return;
  }
  document.getElementById("roomSettingsPanel")?.remove();
  roomTitleEl.textContent = data.title;
  document.title = data.title;
  renderWorld();
}

const ROOM_PASSPHRASE_ERRORS = {
  "same as admin passphrase": "管理者合言葉と同じにはできません",
};

async function applyRoomPassphrase(value) {
  if (!value) { alert("参加者合言葉を入力してください"); return; }
  if (!confirm(`参加者合言葉を「${value}」に変更しますか？\n入室中の人はそのまま続けられます。新しく入室する人には新しい合言葉が必要です`)) return;
  const passphrase = localStorage.getItem("mokumoku-passphrase") || "";
  try {
    const res = await fetch("/admin/room-passphrase", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passphrase, value, actorId: clientId }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      alert(ROOM_PASSPHRASE_ERRORS[data.error] || "参加者合言葉の変更に失敗しました");
      return;
    }
  } catch {
    alert("参加者合言葉の変更に失敗しました");
    return;
  }
  document.getElementById("roomSettingsPanel")?.remove();
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
  document.getElementById("roomSettingsPanel")?.remove();
  // 操作した本人はジッター待ちせず即時反映。以後のpollで同じバージョンを受け取っても
  // scheduleRoomImageRefreshが「既に反映済み」と判定して再取得しないよう基準値も更新する
  roomImageVersion = data.version;
  pendingImageVersion = null;
  selfRoomImageSrc = `/room-image.webp?v=${data.version}`;
  renderWorld();
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
  document.getElementById("roomSettingsPanel")?.remove();
  roomState = data.state;
  renderWorld();
}

const AREA_ERRORS = {
  "invalid url": "URLの形式が正しくありません(https://から始まる有効なURLを入力してください)",
  "invalid video": "YouTubeの動画URLとして読み取れませんでした",
  "video unavailable": "その動画の情報を取得できませんでした(限定公開・削除済みかもしれません)",
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

// 置いてあるエリア1件ぶんの行。中身を差し替えられる種別(YouTubeルーム)は差し替え欄も持つ
function buildAreaRow(a) {
  const spec = areaSpec(a.kind);
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
  if (!spec.swapHint) return row;
  const swapInput = document.createElement("input");
  swapInput.type = "text";
  swapInput.placeholder = spec.swapHint;
  const swap = () => changeArea({ action: "update", id: a.id, kind: a.kind, url: swapInput.value.trim() });
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
  kindSelect.innerHTML = areaKinds()
    .map(k => `<option value="${k.key}">${k.area.label}</option>`).join("");
  const urlInput = document.createElement("input");
  urlInput.type = "text";
  const nameInput = document.createElement("input");
  nameInput.type = "text";
  // 接続方式の選択(ピアの通常/Redis版など)。選択肢を持つ種別のときだけ出す
  const typeSelect = document.createElement("select");
  const addBtn = document.createElement("button");
  addBtn.type = "button";
  const syncKind = () => {
    const spec = areaSpec(kindSelect.value);
    // URLが要らない種別(時計など)ではURL欄ごと消す。空欄を残すと何を入れる欄か分からない
    urlInput.hidden = !spec.needsUrl;
    urlInput.placeholder = spec.urlHint;
    nameInput.placeholder = spec.nameHint;
    typeSelect.innerHTML = (spec.typeOptions || [])
      .map(([value, label]) => `<option value="${value}">${label}</option>`).join("");
    typeSelect.hidden = !spec.typeOptions;
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
  const spec = areaSpec(body.kind);
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
    if (!res.ok) { alert(errorText(body.kind, data.error, AREA_ERRORS)); return; }
    // サムネは取れたがoEmbedが拒否した動画、またはX-Frame-Options/CSPが拒否と分かったページ。
    // 多くは埋め込み禁止で、マスには置けても表示・再生できない
    if (data.embeddable === false && spec.embedWarning) alert(spec.embedWarning);
  } catch {
    alert("操作に失敗しました");
    return;
  }
  document.getElementById("worldPanel")?.remove();
  await poll();
  // 追加したらパネルは閉じたままにして、置いたものをすぐ見られるようにする。
  // 撤去・差し替えは続けて操作することが多いので、更新後の一覧を出し直す
  if (body.action !== "add") toggleWorldPanel();
}

const NPC_ERRORS = {
  "name and task required": "名前とやることを入力してください",
  "invalid image": "画像として読み込めませんでした",
  "invalid kind": "不明な種別です",
  "not found": "そのNPCは見つかりませんでした",
  "admin required": "管理者合言葉が必要です",
};

// サーバーのエラーコードを説明文にする。種別固有のもの(動画が取れない等)は種別側の説明を優先する
function errorText(kind, code, common) {
  return KINDS[kind]?.errors?.[code] || common[code] || "操作に失敗しました";
}

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
  const spec = npcSpec(e.kind);
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
  kindSelect.innerHTML = npcKinds()
    .map(k => `<option value="${k.key}">${k.npc.label}</option>`).join("");
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
    const spec = npcSpec(kindSelect.value);
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
    const spec = npcSpec(kindSelect.value);
    const name = nameInput.value.trim();
    const task = taskInput.value.trim();
    const url = urlInput.value.trim();
    if (spec.needsTask && (!name || !task)) { alert("名前とやることを入力してください"); return; }
    if (spec.needsUrl && !url) { alert(spec.missingUrl); return; }
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
  const spec = npcSpec(body.kind);
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
    if (!res.ok) { alert(errorText(body.kind, data.error, NPC_ERRORS)); return; }
    // サムネは取れたがoEmbedが拒否した動画(埋め込み禁止の可能性)。changeAreaと同じ扱い
    if (data.embeddable === false && spec.embedWarning) alert(spec.embedWarning);
  } catch {
    alert("操作に失敗しました");
    return;
  }
  if (data.roomFull) { alert("満室です。NPCを入れる空き部屋がありません"); return; }
  document.getElementById("npcPanel")?.remove();
  await poll();
  // 追加したらパネルは閉じたままにして、置いたものをすぐ見られるようにする。
  // 撤去・差し替えは続けて操作することが多いので、更新後の一覧を出し直す
  if (body.action !== "add") toggleNpcPanel();
}
