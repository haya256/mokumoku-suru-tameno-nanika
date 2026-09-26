// 在室者一覧と、入室・編集・退室のフォーム
function renderBoard(entries) {
  lastEntries = entries;
  renderWorld();
  updateMyStatus();
  // 自分のルームの行に、つながった相手ルームの行を続ける
  const rows = [
    ...entries.map(e => ({ e, room: `Room ${e.room}`, local: true })),
    ...peerAreas().flatMap(p => (p.board || []).map(e => ({ e, room: `${p.name} #${e.room}`, local: false }))),
  ];
  // 時計やカレンダーなどの置き物NPCは開始・終了時刻を持たない。
  // 参加者とは分けて「その他」に、行を分けず1か所にまとめて並べる
  const friends = rows.filter(({ e }) => occupantKind(e.kind).hasSchedule);
  const others = rows.filter(({ e }) => !occupantKind(e.kind).hasSchedule);
  othersHeadingEl.style.display = others.length ? "" : "none";
  othersEl.innerHTML = "";
  others.forEach(({ e, room, local }) => {
    const span = document.createElement("span");
    span.className = local ? "other" : "other remote";
    span.innerHTML = `<span class="room">${esc(room)}</span><span class="who">${esc(e.name)}</span>`;
    othersEl.appendChild(span);
  });
  if (friends.length === 0) {
    entriesEl.innerHTML = `<div class="empty">まだ誰ももくもくしていません</div>`;
    return;
  }
  entriesEl.innerHTML = "";
  friends.forEach(({ e, room, local }) => {
    const div = document.createElement("div");
    div.className = local ? "entry" : "entry remote";
    div.innerHTML = `<span class="room">${esc(room)}</span><span class="who">${esc(e.name)}</span><span class="when">${esc(e.start)}〜${esc(e.end || "?")}</span><span class="what">${esc(e.task)}</span>`;
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

// 入室状態に応じてフォームを切替:
//   入室前     → 入室フォームのみ(チャット不可)
//   入室中     → ステータス+編集/送信/退室ボタン+チャット
//   編集モード → 入室フォーム(ボタンは「更新」)。チャットは編集を終えるまで不可
function updateMyStatus() {
  const mine = lastEntries.find(e => e.id === clientId);
  if (mine) {
    // 終了時刻が未定のときは「〜？」と出す
    myStatusEl.textContent = `🟢 ${mine.name}　⏰ ${mine.start}〜${mine.end || "？"}　📝 ${mine.task}`;
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

taskEl.addEventListener("input", () => {
  if (taskEl.value && !startEl.value) startEl.value = nowHHMM();
});

joinBtn.addEventListener("click", async () => {
  const name = nameEl.value.trim();
  const task = taskEl.value.trim();
  if (!name) { alert("もくもくネームを入力してください"); nameEl.focus(); return; }
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
  const result = await postJson("/board/join", { id: clientId, seat: seatToken(), name, task, start: startEl.value, end: endEl.value, ...(image && { image }) });
  if (!result) return;
  if (result.roomFull) {
    alert("満室です。空きが出るまでお待ちください");
    return;
  }
  if (result.error === "not your seat") {
    alert(NOT_YOUR_SEAT_MESSAGE);
    return;
  }
  if (result.error) {
    alert("入室に失敗しました: " + result.error);
    return;
  }
  if (result.seatToken) localStorage.setItem("mokumoku-seat", result.seatToken);
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
  const result = await postJson("/board/leave", { id: clientId, seat: seatToken() });
  if (!result) return;
  if (result.error === "not your seat") { alert(NOT_YOUR_SEAT_MESSAGE); return; }
  localStorage.removeItem("mokumoku-seat");
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
