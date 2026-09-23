// ふつうのキャラ。実参加者と基本NPC(名前・やること・画像を管理者が自由入力)がこれで描かれる。
// kind未指定の住人や知らない種別もここにフォールバックする(occupantKind参照)
registerKind({
  key: "basic",
  // 開始・終了時刻を持つ(在室者一覧に出す)。時計やカレンダーなどの置き物NPCには無い
  hasSchedule: true,

  renderCell(cell, o, { tile, roomLabel, charaUrl }) {
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
    openStatusOnClick(chara, o, portrait, tile, roomLabel);
    const badge = buildBadge(o.name);
    badge.title = o.task;
    cell.append(chara, badge);
  },

  renderStatus(container, o, roomLabel) {
    appendStatusRows(container, [
      ["ルーム", statusRoomText(o, roomLabel)],
      ["時間", `${o.start || "?"}〜${o.end || "?"}`],
      ["やること", o.task || "(未入力)"],
    ]);
  },

  npc: {
    order: 0,
    label: "基本NPC", addLabel: "入室させる", delLabel: "片付ける",
    confirm: "このNPCを片付けますか？",
    needsTask: true, needsImage: true, nameHint: "NPCの名前",
  },
});
