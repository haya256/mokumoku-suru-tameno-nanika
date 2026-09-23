// つながった相手のもくもくルーム。中身は自分のルームと同じ9部屋なので renderRoomInto を使い回す。
// 在室者一覧やチャットへのマージ(peerAreas)はcore.js側が受け持つ
const PEER_STATUS = { false: "接続できません", null: "接続中…", undefined: "接続中…" };

registerKind({
  key: "peer",

  renderTile(tile, area, { focused, visible }) {
    setTileImage(tile, area, area.roomImageVersion);
    setClass(tile.el, `tile peer${area.ok === false ? " offline" : ""}${focused}`);
    tile.label.textContent = area.ok === true ? `${area.name} (${(area.board || []).length}人)` : area.name;
    tile.status.hidden = area.ok === true;
    tile.status.textContent = PEER_STATUS[area.ok] || "";
    renderRoomInto(tile, area.board, peerCharaUrl(area.id), area.name, visible);
  },

  area: {
    label: "もくもくルーム", needsUrl: true, addLabel: "つなぐ", delLabel: "解除",
    confirm: "この接続を解除しますか？", urlHint: "相手ルームのURL (https://...)",
    nameHint: "表示名 (任意)", missingUrl: "相手ルームのURLを入力してください",
    // fork型はelm200版(FastAPI+Redis)向けの読み替えアダプタを使う。向こうのRedis消費を抑えるため
    // 巡回間隔も別扱いになる(config/settings.jsonのworld.fork_poll_interval_sec)
    typeOptions: [["native", "通常"], ["fork", "Redis版"]],
    title: a => a.url || "",
    text: a => a.type === "fork" ? `${a.name} (Redis版)` : a.name,
  },

  errors: {
    "already connected": "そのルームとは既につながっています",
  },
});
