// 管理者が置いた掛け時計。エリアにも部屋NPCにもなれる。出すのは見ている人の手元の時刻
// (サーバーの時刻ではない)。針はCSSアニメーションが回すので、ここでやるのは位相合わせだけ。
// 毎秒動くJSは存在しない

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

// document.createElement("svg") はHTMLUnknownElementになって何も描画されないので、
// 文字列をinnerHTMLで流し込んでSVGとして解釈させる
function buildClockFace() {
  const face = document.createElement("div");
  face.className = "clock-face";
  face.innerHTML = CLOCK_FACE_SVG;
  const hands = { hour: face.querySelector(".hand.hour"), min: face.querySelector(".hand.min"),
                  sec: face.querySelector(".hand.sec") };
  return { face, hands };
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

registerKind({
  key: "clock",

  buildTileParts(tile) {
    const { face, hands } = buildClockFace();
    tile.hands = hands;
    return [face];
  },

  renderTile(tile, area, { focused, visible }) {
    setClass(tile.el, `tile clock${focused}`);
    tile.label.textContent = area.name;
    tile.status.hidden = true;
    // 隠れている間は触らない。display:none はCSSアニメーションを破棄するので、ここで位相を
    // 書いても見えた瞬間に「書いた時刻」のまま復活して、ずれた時計が動き続けることになる。
    // 見えたときに「いま針が指している時刻」を確かめて、違っていれば直す
    if (visible && clockNeedsSync(tile.hands)) syncClockHands(tile.hands);
  },

  // 部屋のセルにはエリアと同じ文字盤を小さく置く。初期位相を合わせたうえで、
  // 見えている間は毎pollずれを確かめ直してもらう(renderRoomIntoのliveCells)
  renderCell(cell, o, { tile, roomLabel }) {
    const { face, hands } = buildClockFace();
    syncClockHands(hands);
    tile.liveCells.set(o.id, () => { if (clockNeedsSync(hands)) syncClockHands(hands); });
    openStatusOnClick(face, o, null, tile, roomLabel);
    cell.append(face, buildBadge(o.name));
  },

  // モーダルは開くたびに新しくSVGを作って一度だけ位相を合わせれば十分
  // (継続的な再同期チェックは部屋セル内表示側だけで行う)
  renderStatus(container, o, roomLabel) {
    appendStatusRows(container, [["ルーム", statusRoomText(o, roomLabel)]]);
    const { face, hands } = buildClockFace();
    container.appendChild(face);
    syncClockHands(hands);
  },

  area: {
    label: "時計", needsUrl: false, addLabel: "置く", delLabel: "片付ける",
    confirm: "この時計を片付けますか？", urlHint: "",
    nameHint: "表示名 (任意/未指定なら「時計」)", missingUrl: "",
    title: () => "見ている人の手元の時刻を表示します",
    text: a => `🕐 ${a.name}`,
  },

  npc: {
    order: 2,
    label: "時計", addLabel: "入室させる", delLabel: "片付ける",
    confirm: "この時計NPCを片付けますか？",
    needsTask: false, needsImage: false, nameHint: "表示名 (任意/未指定なら「時計」)",
  },
});
