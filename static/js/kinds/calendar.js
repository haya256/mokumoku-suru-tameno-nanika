// 管理者が置いたカレンダー。エリアにも部屋NPCにもなれる。出すのは見ている人の手元の日付
// (サーバーでもタイムゾーン指定でもない)。時計と違って連続アニメーションが無いので、
// 日付が変わったときだけ書き直せば足りる
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

// 日付が変わったかどうかの比較キー。エリアとNPCの両方で「日付が変わったときだけ再描画する」ために使う
function calendarDateKey(date) {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

registerKind({
  key: "calendar",

  // 時計と違ってCSSアニメーションを使わないので参照保持の必要はなく、
  // 日付が変わったときだけ丸ごと書き換える(calendarKeyで判定)
  buildTileParts(tile) {
    const calFace = document.createElement("div");
    calFace.className = "calendar-face";
    tile.calendarFace = calFace;
    tile.calendarKey = null;
    return [calFace];
  },

  resetTile(tile) {
    tile.calendarKey = null;
  },

  renderTile(tile, area, { focused }) {
    setClass(tile.el, `tile calendar${focused}`);
    tile.label.textContent = area.name;
    tile.status.hidden = true;
    const today = new Date();
    const key = calendarDateKey(today);
    if (tile.calendarKey !== key) {
      tile.calendarKey = key;
      tile.calendarFace.innerHTML = buildCalendarFaceHTML(today);
    }
  },

  // 部屋のセルにはエリアと同じ文字盤(コンパクト/月グリッドの切り替えもCSSで無改修のまま流用)を小さく置く
  renderCell(cell, o, { tile, roomLabel }) {
    const face = document.createElement("div");
    face.className = "calendar-face";
    face.innerHTML = buildCalendarFaceHTML(new Date());
    openStatusOnClick(face, o, null, tile, roomLabel);
    cell.append(face, buildBadge(o.name));
  },

  // 他の入退室が無くても、日付が変わったら部屋を描き直してもらう
  cellFingerprint() {
    return calendarDateKey(new Date());
  },

  // 月グリッドを表示する。時間・やることは意味を持たないので出さない
  renderStatus(container, o, roomLabel) {
    appendStatusRows(container, [["ルーム", statusRoomText(o, roomLabel)]]);
    const today = new Date();
    const face = document.createElement("div");
    face.className = "calendar-face";
    face.innerHTML = buildCalendarGrid(today.getFullYear(), today.getMonth(), today);
    container.appendChild(face);
  },

  area: {
    label: "カレンダー", needsUrl: false, addLabel: "置く", delLabel: "片付ける",
    confirm: "このカレンダーを片付けますか？", urlHint: "",
    nameHint: "表示名 (任意/未指定なら「カレンダー」)", missingUrl: "",
    title: () => "見ている人の手元の日付を表示します",
    text: a => `📅 ${a.name}`,
  },

  npc: {
    order: 1,
    label: "カレンダー", addLabel: "入室させる", delLabel: "片付ける",
    confirm: "このカレンダーNPCを片付けますか？",
    needsTask: false, needsImage: false, nameHint: "表示名 (任意/未指定なら「カレンダー」)",
  },
});
